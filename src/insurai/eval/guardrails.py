"""guardrails slice (spec 08 eval hooks; reported, not gated): the full graph on guarantee and conflict items.

Items come from eval/datasets/guardrails.jsonl: a row with `ref` reuses that dataset's item by id (EVAL029
and EVAL030 from policy_clauses.jsonl) and adds this slice's tags; other rows are items of their own.
Phase 1 runs every turn; phase 2 runs the V7 judge on the answers (eval/groundedness.py).

Metrics: not_refused (items with must_refuse false that got an answer, not a refusal); for `guarantee`
items, s15_cited and mandated_wording; for `conflict` items, conflict_rendered (the precedence sentence);
V1–V7 pass rates from each turn's final verify event; and the V7 judge in the eval.
"""

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from insurai.agent import graph as agent_graph
from insurai.agent.checkpoint import memory_saver
from insurai.agent.runner import pending_review, resume, run_turn
from insurai.agent.schemas import Evidence
from insurai.eval.groundedness import final_checks, judge_rows, v7_metrics, verifier_pass_rates
from insurai.guardrails.verify import labels_in, mandated_span
from insurai.observability import get_logger
from insurai.rules.schemas import ReviewDecision
from insurai.settings import ROOT
from insurai.tools.messages import guardrails
from insurai.tools.schemas import Persona

log = get_logger(__name__)

SLICE = "guardrails"
DATASETS = ROOT / "eval" / "datasets"
DATASET = DATASETS / "guardrails.jsonl"
CITED_SECTION = "§15"


class GuardrailItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    persona: Persona = "claims_agent"
    principal_id: str | None = None
    turns: list[dict[str, str]]
    must_refuse: bool = False
    tags: list[str] = Field(default_factory=list)


def load_items() -> list[GuardrailItem]:
    items: list[GuardrailItem] = []
    for line in DATASET.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if ref := row.get("ref"):
            base = _find(ref, row["id"])
            row = {**base, "tags": list(dict.fromkeys([*base.get("tags", []), *row.get("tags", [])]))}
        items.append(GuardrailItem.model_validate(row))
    return items


def _find(dataset: str, item_id: str) -> dict[str, Any]:
    for line in (DATASETS / dataset).read_text(encoding="utf-8").splitlines():
        if line.strip() and (row := json.loads(line))["id"] == item_id:
            return dict(row)
    raise KeyError(f"{item_id} not in {dataset}")


def is_refusal(answer: str) -> bool:
    texts = [t.split("{", 1)[0].strip() for t in guardrails()["refusals"].values()]
    return any(t and answer.strip().startswith(t) for t in texts)


def score(item: GuardrailItem, answer: str) -> dict[str, Any]:
    g = guardrails()
    row: dict[str, Any] = {"refused": is_refusal(answer)}
    if "guarantee" in item.tags:
        row["s15_cited"] = any(CITED_SECTION in label for label in labels_in(answer))
        row["mandated_wording"] = mandated_span(answer) is not None
    if "conflict" in item.tags:
        row["conflict_rendered"] = g["conflict_rendering"]["precedence_sentence"] in answer
    return row


def run_slice() -> dict[str, Any]:
    items = load_items()
    graph = agent_graph.build_graph(memory_saver())
    rows: list[dict[str, Any]] = []
    evidence: dict[str, list[Evidence]] = {}
    for item in items:  # phase 1: answers
        thread = f"eval-{SLICE}-{item.id}"
        row: dict[str, Any] = {"id": item.id, "tags": item.tags, "must_refuse": item.must_refuse}
        try:
            result = run_turn(graph, thread, item.turns[-1]["content"], item.persona, item.principal_id)
            if pending_review(graph, thread) is not None:
                result = resume(graph, thread, ReviewDecision(action="approve", note="eval auto-approve"))
            values = graph.get_state({"configurable": {"thread_id": thread}}).values
            plan = values.get("plan")
            evidence[item.id] = list(values.get("evidence") or [])
            row |= {
                "answer": result.answer_markdown,
                "intents": [i.type for i in plan.intents] if plan else [],
                "checks": final_checks(result.trace),
                **score(item, result.answer_markdown),
            }
        except Exception as exc:  # one failing item must not sink the slice
            log.exception("guardrails %s failed", item.id)
            row["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
    judge_rows(rows, evidence)  # phase 2: the V7 judge
    for row in rows:
        log.info("guardrails %s %s", row["id"], {k: v for k, v in row.items() if k != "answer"})
    return {"metrics": metrics(rows), "items": rows}


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def share(key: str, subset: list[dict[str, Any]]) -> float | None:
        scored = [r for r in subset if key in r]
        return round(sum(bool(r[key]) for r in scored) / len(scored), 4) if scored else None

    answerable = [r for r in rows if not r["must_refuse"]]
    not_refused = [r for r in answerable if "refused" in r]
    return {
        "items": len(rows),
        "not_refused": round(sum(not r["refused"] for r in not_refused) / len(answerable), 4)
        if answerable
        else None,
        "s15_cited": share("s15_cited", rows),
        "mandated_wording": share("mandated_wording", rows),
        "conflict_rendered": share("conflict_rendered", rows),
        "verifier_pass": verifier_pass_rates(rows),
        **v7_metrics(rows),
        "errors": [r["id"] for r in rows if "error" in r],
    }
