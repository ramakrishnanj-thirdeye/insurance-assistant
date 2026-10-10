"""Full-graph eval slices (spec 11): policy_clauses_e2e and comparisons; adversarial reuses `run_items`.

Phase 1 runs every item through the in-process graph (InMemorySaver, a fresh thread per item, a review
auto-approved) and holds each item's evidence aside; phase 2 runs the correctness judge
(judge_correctness.md, score ≥ 4 correct) on items with a gold answer and the V7 groundedness judge on
model-written answers, so a local Ollama loads the judge once (ADR-006 amendment).

Metrics per slice: correctness, faithfulness and V7 (eval/groundedness.py), citation_accuracy (cites ≥ 1
gold label, faq pairs matched by section, and no label outside the evidence), refused (any refusal);
policy_clauses_e2e also reports unanswerable probes that abstained. Counts for every proportion.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from insurai.agent import graph as agent_graph
from insurai.agent.checkpoint import memory_saver
from insurai.agent.runner import pending_review, resume, run_turn
from insurai.agent.schemas import Evidence, TraceEvent
from insurai.eval import correctness
from insurai.eval.groundedness import final_checks, judge_rows, v7_metrics, verifier_pass_rates
from insurai.eval.retrieval import UNANSWERABLE, any_gold
from insurai.eval.review import AUTO_APPROVE
from insurai.eval.stats import count, prop
from insurai.guardrails.verify import labels_in
from insurai.observability import get_logger
from insurai.settings import ROOT
from insurai.tools.messages import guardrails
from insurai.tools.schemas import Persona

log = get_logger(__name__)

DATASETS = ROOT / "eval" / "datasets"
DRAFT = "draft"
LOGGED = ("refused", "citation_ok", "error")  # per-item log fields; judge scores are never logged


class E2EItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    slice: str
    persona: Persona = "claims_agent"
    principal_id: str | None = None
    turns: list[dict[str, str]]
    gold_answer: str | None = None
    gold_sources: list[str] = Field(default_factory=list)
    must_refuse: bool = False
    refusal_code: str | None = None
    tags: list[str] = Field(default_factory=list)
    labels: dict[str, Any] = Field(default_factory=dict)

    @property
    def question(self) -> str:
        return self.turns[-1]["content"]


def load_items(name: str, slice_name: str | None = None, datasets: Path = DATASETS) -> list[E2EItem]:
    rows = [
        json.loads(line)
        for line in (datasets / name).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return [E2EItem.model_validate(r) for r in rows if slice_name is None or r.get("slice") == slice_name]


# --- refusals ------------------------------------------------------------------------------------------


def refusal_prefixes() -> dict[str, str]:
    """Refusal code -> its text up to the first placeholder (NOT_FOUND names the entity)."""
    return {code: text.split("{", 1)[0].strip() for code, text in guardrails()["refusals"].items()}


def refusal_of(answer: str, trace: list[TraceEvent] | None = None) -> str | None:
    """The refusal code of an answer: the input guard's code when it blocked the turn, else the refusal
    text the answer starts with; None for an answer."""
    for event in trace or []:
        if event.name == "input_guard" and event.data.get("allowed") is False and event.data.get("code"):
            return str(event.data["code"])
    text = answer.strip()
    for code, prefix in refusal_prefixes().items():
        if prefix and text.startswith(prefix):
            return code
    return None


def refusal_text_in(code: str, answer: str) -> bool:
    prefix = refusal_prefixes().get(code, "")
    return bool(prefix) and prefix in answer


# --- phase 1 and 2 ---------------------------------------------------------------------------------------


def run_items(
    items: list[E2EItem], slice_name: str
) -> tuple[list[dict[str, Any]], dict[str, list[Evidence]]]:
    """Phase 1: every item through the graph. Rows carry the answer, intents, citations, checks, refusal
    code and the trace's turn latency; evidence is returned aside (not written to the report)."""
    graph = agent_graph.build_graph(memory_saver())
    rows: list[dict[str, Any]] = []
    evidence: dict[str, list[Evidence]] = {}
    for item in items:
        thread = f"eval-{slice_name}-{item.id}"
        row: dict[str, Any] = {
            "id": item.id,
            "tags": item.tags,
            "draft": DRAFT in item.tags,
            "must_refuse": item.must_refuse,
        }
        try:
            result = None
            for turn in item.turns:
                if turn["role"] == "user":
                    result = run_turn(graph, thread, turn["content"], item.persona, item.principal_id)
            if pending_review(graph, thread) is not None:
                result = resume(graph, thread, AUTO_APPROVE)
            assert result is not None, "item has no user turn"
            values = graph.get_state({"configurable": {"thread_id": thread}}).values
            plan = values.get("plan")
            evidence[item.id] = list(values.get("evidence") or [])
            row |= {
                "answer": result.answer_markdown,
                "intents": [i.type for i in plan.intents] if plan else [],
                "citations": labels_in(result.answer_markdown),
                "checks": final_checks(result.trace),
                "refused": refusal_of(result.answer_markdown, result.trace),
                "trace_text": _trace_text(result.trace),
            }
        except Exception as exc:  # one failing item must not sink the slice
            log.exception("%s %s failed", slice_name, item.id)
            row["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
    return rows, evidence


def judge_phase(
    rows: list[dict[str, Any]],
    items: list[E2EItem],
    evidence: dict[str, list[Evidence]],
    gold_of: Callable[[E2EItem], str | None] = lambda i: i.gold_answer,
) -> None:
    """Phase 2: correctness on items with a gold answer, then V7 on model-written answers."""
    golds = {i.id: (i.question, gold) for i in items if (gold := gold_of(i))}
    correctness.judge_rows(rows, golds)
    judge_rows(rows, evidence)


def citation_ok(item: E2EItem, row: dict[str, Any], evidence: list[Evidence]) -> bool | None:
    """Cites at least one gold label and none outside the evidence; None without gold sources."""
    if not item.gold_sources or "answer" not in row:
        return None
    known = {ref.label for ev in evidence for ref in ev.sources}
    cited = row.get("citations") or []
    return any(any_gold(c, item.gold_sources) for c in cited) and all(c in known for c in cited)


def run_answer_slice(slice_name: str, items: list[E2EItem]) -> dict[str, Any]:
    """A slice of answerable items (and unanswerable probes): correctness, faithfulness, citations."""
    rows, evidence = run_items(items, slice_name)
    by_id = {i.id: i for i in items}
    for row in rows:
        row["citation_ok"] = citation_ok(by_id[row["id"]], row, evidence.get(row["id"], []))
    judge_phase(rows, items, evidence)
    for row in rows:
        log.info("%s %s %s", slice_name, row["id"], {k: row.get(k) for k in LOGGED})
        row.pop("trace_text", None)
    return {**answer_metrics(rows, by_id), "items": rows}


def answer_metrics(rows: list[dict[str, Any]], items: dict[str, E2EItem]) -> dict[str, Any]:
    counts: dict[str, list[int]] = {}
    probes = [r for r in rows if UNANSWERABLE in items[r["id"]].tags]
    answerable = [r for r in rows if r not in probes]
    metrics: dict[str, Any] = {"items": len(rows), "draft_items": sum(r["draft"] for r in rows)}
    metrics |= correctness.correctness_metrics(answerable, counts)
    prop(metrics, counts, "citation_accuracy", *count(r.get("citation_ok") for r in answerable))
    prop(
        metrics, counts, "refused", *count(r.get("refused") is not None for r in answerable if "answer" in r)
    )
    if probes:
        prop(metrics, counts, "probes_abstained", *count(r.get("refused") is not None for r in probes))
    metrics |= v7_metrics(rows, counts)
    metrics["verifier_pass"] = verifier_pass_rates(rows)
    metrics["wrong"] = [
        r["id"] for r in answerable if "error" in r or correctness.is_correct(r) is False or r.get("refused")
    ]
    metrics["errors"] = [r["id"] for r in rows if "error" in r]
    return {"metrics": metrics, "counts": counts}


def _trace_text(trace: list[TraceEvent]) -> str:
    """The trace as text, for the adversarial PII check (raw PII must not reach the trace)."""
    return json.dumps([e.model_dump() for e in trace], ensure_ascii=False, default=str)


# --- slices ----------------------------------------------------------------------------------------------

CLAUSES_SLICE = "policy_clauses_e2e"
COMPARISONS_SLICE = "comparisons"


def run_clauses() -> dict[str, Any]:
    items = load_items("seed_rag.jsonl", "policy_clauses") + load_items(
        "policy_clauses.jsonl", "policy_clauses"
    )
    return run_answer_slice(CLAUSES_SLICE, items)


def run_comparisons() -> dict[str, Any]:
    return run_answer_slice(COMPARISONS_SLICE, load_items("comparisons.jsonl"))
