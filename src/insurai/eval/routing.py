"""Routing slice (spec 11 metrics; spec 06 AC-06-02): intent-set accuracy and entity exact match.

Single-turn items run input_guard → resolve_context → planner only (the same node functions as the graph).
multi_turn items run the full graph on an InMemorySaver, auto-approving reviews through `resume()`, and are
scored on their last turn.
"""

import random
import uuid
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, ConfigDict

from insurai.agent import graph as agent_graph
from insurai.agent.checkpoint import memory_saver
from insurai.agent.runner import pending_review, resume, run_turn
from insurai.agent.schemas import Plan
from insurai.eval.review import AUTO_APPROVE
from insurai.observability import get_logger
from insurai.settings import ROOT
from insurai.tools.schemas import Persona

log = get_logger(__name__)

SLICE = "routing"
DATASETS = ROOT / "eval" / "datasets"
SOURCES = (
    "sql_facts",
    "policy_clauses",
    "seed_rag",
    "claim_analysis_seed",
    "claim_analysis",
    "multi_turn",
    "analytics",
)
SEED = 42


class RoutingItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    slice: str
    persona: Persona = "claims_agent"
    principal_id: str | None = None
    turns: list[dict[str, str]]
    expected_route: list[str]
    expected_entities: dict[str, str]


def load_items(datasets: Path = DATASETS) -> list[RoutingItem]:
    """Every golden item with an expected route, deduplicated by id."""
    items: dict[str, RoutingItem] = {}
    for name in SOURCES:
        path = datasets / f"{name}.jsonl"
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = RoutingItem.model_validate_json(line)
                items.setdefault(item.id, item)
    return list(items.values())


def predicted(plan: Plan | None) -> tuple[list[str], dict[str, str]]:
    """(intent types, union of entities) of a final plan; the first intent setting a key wins."""
    if plan is None:
        return [], {}
    entities: dict[str, str] = {}
    for intent in plan.intents:
        for key, value in intent.entities.set_fields().items():
            entities.setdefault(key, value)
    return [i.type for i in plan.intents], entities


def score_item(
    expected_route: list[str], expected_entities: dict[str, str], route: list[str], entities: dict[str, str]
) -> tuple[bool, bool]:
    intent_ok = set(route) == set(expected_route)
    entity_ok = all(entities.get(k) == v for k, v in expected_entities.items())
    return intent_ok, entity_ok


def plan_only(text: str, persona: Persona, principal_id: str | None, thread_id: str) -> Plan | None:
    """The graph's routing prefix without workers: guard, resolve, then fast path or planner."""
    config: Any = {"configurable": {"thread_id": thread_id}}
    state: dict[str, Any] = {
        "messages": [HumanMessage(text)],
        "persona": persona,
        "principal_id": principal_id,
    }
    state |= agent_graph.input_guard(state)  # type: ignore[arg-type]
    if not state["guard"].allowed:
        return None
    state |= agent_graph.resolve_context(state, config)  # type: ignore[arg-type]
    if state.get("refusal"):
        return None
    if state.get("fast_path"):
        return state["plan"]
    return agent_graph.planner(state, config)["plan"]  # type: ignore[arg-type]


def plan_multi_turn(item: RoutingItem, graph: Any) -> Plan | None:
    thread_id = f"eval-{item.id}-{uuid.uuid4().hex[:6]}"
    for turn in item.turns:
        run_turn(graph, thread_id, turn["content"], item.persona, item.principal_id)
        if pending_review(graph, thread_id) is not None:
            resume(graph, thread_id, AUTO_APPROVE)
    return graph.get_state({"configurable": {"thread_id": thread_id}}).values.get("plan")


def run_slice(sample: int | None = None) -> dict[str, Any]:
    items = load_items()
    if sample:
        items = random.Random(SEED).sample(items, min(sample, len(items)))
    graph = agent_graph.build_graph(memory_saver())
    rows: list[dict[str, Any]] = []
    for item in items:
        try:
            if len(item.turns) > 1:
                plan = plan_multi_turn(item, graph)
            else:
                plan = plan_only(item.turns[0]["content"], item.persona, item.principal_id, f"eval-{item.id}")
            error = None
        except Exception as exc:  # one failing item must not sink the slice; it scores as wrong
            log.exception("routing item %s failed", item.id)
            plan, error = None, f"{type(exc).__name__}: {exc}"
        route, entities = predicted(plan)
        intent_ok, entity_ok = score_item(item.expected_route, item.expected_entities, route, entities)
        rows.append(
            {
                "id": item.id,
                "slice": item.slice,
                "expected_route": item.expected_route,
                "route": route,
                "expected_entities": item.expected_entities,
                "entities": entities,
                "clarification": plan.clarification if plan else None,
                "intent_ok": intent_ok,
                "entity_ok": entity_ok,
                "error": error,
            }
        )
        log.info("routing %s intent=%s entity=%s route=%s", item.id, intent_ok, entity_ok, route)
    n = len(rows)
    by_slice: dict[str, dict[str, float]] = {}
    for name in sorted({r["slice"] for r in rows}):
        sub = [r for r in rows if r["slice"] == name]
        by_slice[name] = {
            "items": len(sub),
            "intent_accuracy": round(sum(r["intent_ok"] for r in sub) / len(sub), 4),
            "entity_exact": round(sum(r["entity_ok"] for r in sub) / len(sub), 4),
        }
    metrics = {
        "items": n,
        "intent_accuracy": round(sum(r["intent_ok"] for r in rows) / n, 4) if n else 0.0,
        "entity_exact": round(sum(r["entity_ok"] for r in rows) / n, 4) if n else 0.0,
        "by_slice": by_slice,
        "wrong": [r["id"] for r in rows if not (r["intent_ok"] and r["entity_ok"])],
    }
    return {"metrics": metrics, "items": rows}
