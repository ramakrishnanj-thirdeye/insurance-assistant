"""claim_analysis slice (spec 11; spec 07 eval hooks): rule outcomes, the review interrupt and the narrative.

Deterministic, per item (no LLM): rule statuses, missing and pending documents, consistency flags and
needs_human_review against `labels` (evaluate_claim).

With the LLM (the dossier subgraph on an InMemorySaver, auto-approving a review):
- review_interrupt: the dossier paused iff the item's mode is assess, the claim needs review and the
  persona is not a customer (spec 06 explain vs assess);
- blocker_mention: share of `labels.must_mention` phrases in the narrative (case-insensitive), per item;
- invented_findings: findings the judge (judge_invented_findings.md) finds in the narrative but not in
  the assessment; invented_findings_free is the share of narratives with none (gated at 1.0).
"""

import json
import uuid
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field

from insurai.agent.checkpoint import memory_saver
from insurai.agent.dossier import build_dossier_graph
from insurai.agent.prompts import load_prompt
from insurai.agent.schemas import Entities, Intent
from insurai.llm.structured import structured_call
from insurai.observability import get_logger
from insurai.rules.engine import evaluate_claim
from insurai.rules.narrative import narrative_input, question_mode
from insurai.rules.schemas import ClaimAssessment, ReviewDecision
from insurai.settings import ROOT
from insurai.tools.schemas import Persona

log = get_logger(__name__)

SLICE = "claim_analysis"
DATASETS = ROOT / "eval" / "datasets"
SOURCES = ("claim_analysis_seed.jsonl", "claim_analysis.jsonl")
AUTO_APPROVE = ReviewDecision(action="approve", note="eval auto-approve")
JUDGE_INSTRUCTION = "Check the narrative."


class ClaimItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    persona: Persona = "claims_agent"
    principal_id: str | None = None
    turns: list[dict[str, str]]
    tags: list[str] = Field(default_factory=list)
    labels: dict[str, Any]

    @property
    def question(self) -> str:
        return self.turns[-1]["content"]


class InventedFindings(BaseModel):
    invented: list[str] = Field(default_factory=list)
    count: int


def load_items(datasets: Path = DATASETS) -> list[ClaimItem]:
    items: list[ClaimItem] = []
    for name in SOURCES:
        path = datasets / name
        if path.exists():
            text = path.read_text(encoding="utf-8")
            items += [ClaimItem.model_validate_json(line) for line in text.splitlines() if line.strip()]
    return items


def score_rules(item: ClaimItem, assessment: ClaimAssessment) -> dict[str, bool]:
    labels = item.labels
    return {
        "rule_status_exact": {r.id: r.status for r in assessment.rules} == labels["expected_rules"],
        "docs_exact": assessment.checklist.missing == labels["expected_missing"]
        and assessment.checklist.pending == labels["expected_pending"],
        "consistency_exact": [c.id for c in assessment.consistency] == labels["expected_consistency"],
        "needs_review_exact": assessment.needs_human_review is labels["needs_human_review"],
    }


def mention_recall(phrases: list[str], narrative: str) -> float:
    if not phrases:
        return 1.0
    text = narrative.casefold()
    return sum(p.casefold() in text for p in phrases) / len(phrases)


def expected_interrupt(item: ClaimItem) -> bool:
    return (
        question_mode(item.question) == "assess"
        and bool(item.labels["needs_human_review"])
        and item.persona != "customer"
    )


def run_dossier(item: ClaimItem, graph: Any) -> tuple[ClaimAssessment | None, bool]:
    """The dossier subgraph for the item's question; returns (final assessment, whether it paused)."""
    intent = Intent(
        id="i1",
        type="claim_analysis",
        entities=Entities(claim_id=item.labels["claim_id"]),
        sub_question=item.question,
        mode=question_mode(item.question),
        question=item.question,
    )
    config: Any = {"configurable": {"thread_id": f"eval-{item.id}-{uuid.uuid4().hex[:6]}"}}
    payload = {
        "intent": intent,
        "persona": item.persona,
        "principal_id": item.principal_id,
        "turn": 1,
        "trace_id": f"eval-{item.id}",
    }
    graph.invoke(payload, config)
    paused = bool(graph.get_state(config).interrupts)
    if paused:
        graph.invoke(Command(resume=AUTO_APPROVE), config)
    assessment = graph.get_state(config).values.get("assessment")
    return assessment, paused


def judge_invented(assessment: ClaimAssessment, narrative: str) -> InventedFindings:
    prompt = load_prompt("judge_invented_findings")
    system = prompt.render(
        assessment_json=json.dumps(narrative_input(assessment), ensure_ascii=False, default=str),
        narrative=narrative,
    )
    messages = [SystemMessage(system), HumanMessage(JUDGE_INSTRUCTION)]
    found, _ = structured_call("judge", InventedFindings, messages, prompt.id, prompt.version)
    return found


def run_slice(with_llm: bool = True) -> dict[str, Any]:
    """Phase 1 generates every narrative (generator and small models); phase 2 judges them all, so a local
    Ollama loads the judge once instead of swapping models on every item (ADR-006 amendment)."""
    items = load_items()
    graph = build_dossier_graph(memory_saver()) if with_llm else None
    rows: list[dict[str, Any]] = []
    finals: dict[str, ClaimAssessment | None] = {}
    for item in items:
        row: dict[str, Any] = {"id": item.id, "draft": "draft" in item.tags}
        result = evaluate_claim(item.labels["claim_id"], item.persona, principal_id=item.principal_id)
        if not isinstance(result, ClaimAssessment):
            row |= {"error": getattr(result, "message", str(result))}
            rows.append(row)
            continue
        row |= score_rules(item, result)
        if graph is not None:
            try:
                final, paused = run_dossier(item, graph)
                narrative = (final.narrative if final else None) or ""
                finals[item.id] = final
                row |= {
                    "review_interrupt": paused == expected_interrupt(item),
                    "blocker_mention": round(
                        mention_recall(item.labels.get("must_mention", []), narrative), 4
                    ),
                    "narrative": narrative,
                }
            except Exception as exc:  # one failing item must not sink the slice
                log.exception("claim_analysis %s failed", item.id)
                row |= {"error": f"{type(exc).__name__}: {exc}"}
        rows.append(row)
    for row in rows:  # phase 2: the judge
        if row["id"] in finals:
            final = finals[row["id"]]
            try:
                judged = judge_invented(final, row["narrative"]) if final else InventedFindings(count=1)
                row |= {"invented_findings": judged.count, "invented": judged.invented}
            except Exception as exc:
                log.exception("claim_analysis judge %s failed", row["id"])
                row |= {"error": f"judge {type(exc).__name__}: {exc}"}
        log.info("claim_analysis %s %s", row["id"], {k: v for k, v in row.items() if k != "narrative"})
    return {"metrics": metrics(rows, with_llm), "items": rows}


def metrics(rows: list[dict[str, Any]], with_llm: bool) -> dict[str, Any]:
    n = len(rows)

    def share(key: str) -> float:
        return round(sum(bool(r.get(key)) for r in rows) / n, 4) if n else 0.0

    out: dict[str, Any] = {
        "items": n,
        "draft_items": sum(r["draft"] for r in rows),
        "rule_status_exact": share("rule_status_exact"),
        "docs_exact": share("docs_exact"),
        "consistency_exact": share("consistency_exact"),
        "needs_review_exact": share("needs_review_exact"),
    }
    if with_llm:
        mentions = [r.get("blocker_mention", 0.0) for r in rows]
        out |= {
            "review_interrupt": share("review_interrupt"),
            "blocker_mention": round(sum(mentions) / n, 4) if n else 0.0,
            "invented_findings": sum(r.get("invented_findings", 0) for r in rows),
            "invented_findings_free": round(sum(r.get("invented_findings") == 0 for r in rows) / n, 4)
            if n
            else 0.0,
        }
    out["wrong"] = [
        r["id"]
        for r in rows
        if r.get("error")
        or not all(r.get(k, True) for k in ("rule_status_exact", "docs_exact", "consistency_exact"))
        or (with_llm and (r.get("blocker_mention", 1.0) < 1.0 or r.get("invented_findings", 0) > 0))
    ]
    return out
