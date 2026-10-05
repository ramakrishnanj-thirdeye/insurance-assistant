"""Workers (spec 06): claim_tools, policy_rag, analytics_sql. Each handles one Send'd intent and appends
Evidence plus trace spans; tool access control stays in the tools.
"""

from typing import Any

from pydantic import BaseModel

from insurai.agent.prompts import template
from insurai.agent.schemas import Evidence, Intent, TraceEvent
from insurai.agent.state import WorkerInput
from insurai.agent.trace import event, now_ms
from insurai.formatting import inr
from insurai.knowledge.coverage import ATTRIBUTE_SECTIONS
from insurai.retrieval.glossary import expand
from insurai.retrieval.schemas import RetrievalResult
from insurai.settings import get_settings
from insurai.tools.base import redact_args
from insurai.tools.knowledge import CoverageCells
from insurai.tools.messages import refusal
from insurai.tools.registry import TOOLS
from insurai.tools.schemas import (
    AccessDenied,
    ClaimView,
    CustomerSummary,
    Disambiguation,
    DocumentChecklist,
    HospitalCheck,
    InteractionHistory,
    NotFound,
    PolicyView,
    ToolContext,
)

WORKER_FOR: dict[str, str] = {
    "claim_status": "claim_tools",
    "claim_documents": "claim_tools",
    "claim_interactions": "claim_tools",
    "policy_details": "claim_tools",
    "hospital_check": "claim_tools",
    "customer_summary": "claim_tools",
    "policy_question": "policy_rag",
    "coverage_compare": "policy_rag",
    "analytics": "analytics_sql",
    "claim_analysis": "claim_dossier",
}
_ATTRIBUTE_FOR_SECTION = {section: attr for attr, section in ATTRIBUTE_SECTIONS.items()}


def tool_context(payload: WorkerInput) -> ToolContext:
    return ToolContext(
        persona=payload["persona"],
        principal_id=payload["principal_id"],
        as_of=get_settings().as_of_date,
        trace_id=payload["trace_id"],
    )


class Recorder:
    """Calls tools for one intent, collecting Evidence and tool/retrieval trace events."""

    def __init__(self, payload: WorkerInput, worker: str) -> None:
        self.ctx = tool_context(payload)
        self.intent: Intent = payload["intent"]
        self.turn = payload["turn"]
        self.worker = worker
        self.evidence: list[Evidence] = []
        self.trace: list[TraceEvent] = []

    def call(self, tool: str, /, **args: Any) -> BaseModel:
        """Call `tool` with `args`; positional-only so a tool argument called `name` cannot collide."""
        start = now_ms()
        result: BaseModel = TOOLS[tool](self.ctx, **args)
        kind = str(getattr(result, "kind", "ok"))
        self.trace.append(
            event(
                "tool",
                tool,
                self.turn,
                start,
                worker=self.worker,
                intent_id=self.intent.id,
                args=redact_args(args),
                result_kind=kind,
                result_size=len(result.model_dump_json()),
            )
        )
        if isinstance(result, RetrievalResult):
            self.trace.append(retrieval_event(result, self.turn, start, self.intent.id))
        self.evidence.append(to_evidence(self.intent.id, self.worker, result))
        return result

    def note(self, kind: str, summary: str) -> None:
        self.evidence.append(
            Evidence(
                intent_id=self.intent.id,
                worker=self.worker,
                kind=kind,
                payload={},
                sources=[],
                summary=summary,
            )
        )

    def output(self, span_start: float) -> dict[str, Any]:
        span = event(
            "node", self.worker, self.turn, span_start, intent_id=self.intent.id, intent=self.intent.type
        )
        return {"evidence": self.evidence, "trace": [*self.trace, span]}


def claim_tools(payload: WorkerInput) -> dict[str, Any]:
    start = now_ms()
    rec = Recorder(payload, "claim_tools")
    e = rec.intent.entities
    match rec.intent.type:
        case "claim_status":
            rec.call("get_claim", claim_id=e.claim_id)
        case "claim_documents":
            rec.call("get_claim_documents", claim_id=e.claim_id)
        case "claim_interactions":
            rec.call("get_claim_interactions", claim_id=e.claim_id)
        case "policy_details":
            policy_id = e.policy_id
            if policy_id is None and e.claim_id:
                claim = rec.call("get_claim", claim_id=e.claim_id)
                policy_id = claim.policy_id if isinstance(claim, ClaimView) else None
            if policy_id:
                rec.call("get_policy", policy_id=policy_id)
        case "hospital_check":
            _hospital(rec)
        case "customer_summary":
            if e.customer_id or e.hospital_name is None:
                rec.call("get_customer_summary", customer_id=e.customer_id)
    return rec.output(start)


def _hospital(rec: Recorder) -> None:
    e = rec.intent.entities
    if e.hospital_id or e.hospital_name:
        rec.call("check_hospital", hospital_id=e.hospital_id, name=e.hospital_name, city=e.city)
        return
    claim = rec.call("get_claim", claim_id=e.claim_id)
    if isinstance(claim, ClaimView) and claim.hospital is not None:
        rec.call("check_hospital", hospital_id=claim.hospital.hospital_id)
    elif isinstance(claim, ClaimView):
        rec.evidence[-1] = rec.evidence[-1].model_copy(
            update={"summary": f"Claim {claim.claim_id} ({claim.policy_type}) has no hospital on record."}
        )


def policy_rag(payload: WorkerInput) -> dict[str, Any]:
    start = now_ms()
    rec = Recorder(payload, "policy_rag")
    e = rec.intent.entities
    if rec.intent.type == "coverage_compare":
        _, hints = expand(rec.intent.sub_question)
        attribute = next((_ATTRIBUTE_FOR_SECTION[s] for s in hints if s in _ATTRIBUTE_FOR_SECTION), None)
        if attribute is not None:
            result = rec.call("get_coverage", product=e.product, attribute=attribute)
            if e.policy_type and isinstance(result, CoverageCells):
                _keep_policy_type(rec, e.policy_type)
    rec.call("search_policy", query=rec.intent.sub_question, product=e.product, policy_type=e.policy_type)
    return rec.output(start)


def _keep_policy_type(rec: Recorder, policy_type: str) -> None:
    ev = rec.evidence[-1]
    cells = [c for c in ev.payload.get("cells", []) if c.get("policy_type") == policy_type]
    labels = {ref["label"] for c in cells for ref in c.get("sources", [])}
    rec.evidence[-1] = ev.model_copy(
        update={
            "payload": {**ev.payload, "cells": cells},
            "sources": [s for s in ev.sources if s.label in labels],
            "summary": f"{len(cells)} {policy_type} products: " + "; ".join(_cell_line(c) for c in cells),
        }
    )


def analytics_sql(payload: WorkerInput) -> dict[str, Any]:
    start = now_ms()
    rec = Recorder(payload, "analytics_sql")
    rec.note("unavailable", template("analytics_unavailable"))  # run_analytics arrives with spec 02 (M6)
    return rec.output(start)


# --- evidence ---------------------------------------------------------------------------------------------


def to_evidence(intent_id: str, worker: str, result: BaseModel) -> Evidence:
    if isinstance(result, NotFound):
        return Evidence(
            intent_id=intent_id,
            worker=worker,
            kind="not_found",
            payload=result.model_dump(),
            sources=[],
            summary=result.message,
        )
    if isinstance(result, AccessDenied):
        return Evidence(
            intent_id=intent_id,
            worker=worker,
            kind="access_denied",
            payload={},
            sources=[],
            summary=refusal("ACCESS_DENIED"),
        )
    if isinstance(result, RetrievalResult):
        payload = {
            "query": result.query,
            "filters": result.filters,
            "confident": result.confident,
            "unfiltered": result.unfiltered,
            "clauses": [
                {"label": h.chunk.citation_label, "product": h.chunk.product, "text": h.chunk.text}
                for h in result.chunks
            ],
        }
        labels = ", ".join(h.chunk.citation_label for h in result.chunks) or "none"
        return Evidence(
            intent_id=intent_id,
            worker=worker,
            kind="RetrievalResult",
            payload=payload,
            sources=result.sources,
            summary=f"Closest clauses: {labels}.",
        )
    sources = list(getattr(result, "sources", []))
    payload = result.model_dump(mode="json", exclude={"sources"})
    return Evidence(
        intent_id=intent_id,
        worker=worker,
        kind="disambiguation" if isinstance(result, Disambiguation) else type(result).__name__,
        payload=payload,
        sources=sources,
        summary=summarise(result),
    )


def summarise(result: BaseModel) -> str:
    """One deterministic sentence per result; used for traces and the abstain answer."""
    match result:
        case ClaimView():
            approved = f", {inr(result.approved_amount)} approved" if result.approved_amount else ""
            return (
                f"Claim {result.claim_id} is {result.claim_status}{approved}; filed {result.claim_date} for "
                f"{inr(result.claim_amount)} under {result.product_name} (policy {result.policy_id})."
            )
        case DocumentChecklist():
            return (
                f"Claim {result.claim_id} documents — missing: {', '.join(result.missing) or 'none'}; "
                f"pending verification: {', '.join(result.pending) or 'none'}; "
                f"rejected: {', '.join(result.rejected) or 'none'}."
            )
        case InteractionHistory():
            latest = (
                f"; latest {result.latest_intent} ({result.latest_sentiment})" if result.latest_intent else ""
            )
            return (
                f"Claim {result.claim_id} has {result.total} interactions{latest}; "
                f"{result.open_escalations} open escalations."
            )
        case PolicyView():
            return (
                f"Policy {result.policy_id} ({result.product_name}) is {result.effective_status} "
                f"(recorded {result.policy_status}); sum insured {inr(result.sum_insured)}; "
                f"waiting period {result.waiting_period_days} days; co-pay {result.co_pay_pct}%; "
                f"deductible {inr(result.deductible)}."
            )
        case CustomerSummary():
            return (
                f"Customer {result.customer_id} has {result.policies_in_force} of {result.policies_total} "
                "policies "
                f"in force and {result.claims_open} open of {result.claims_total} claims."
            )
        case HospitalCheck():
            return f"{result.hospital_name} ({result.hospital_id}, {result.city}) is {result.network_status}."
        case Disambiguation():
            return result.message
        case CoverageCells():
            return "; ".join(_cell_line(c.model_dump(mode="json")) for c in result.cells)
    return type(result).__name__


def _cell_line(cell: dict[str, Any]) -> str:
    return f"{cell['product']}: {cell['text'][:160]}"


def retrieval_event(result: RetrievalResult, turn: int, start: float, intent_id: str) -> TraceEvent:
    return event(
        "retrieval",
        "search_policy",
        turn,
        start,
        intent_id=intent_id,
        filters=result.filters,
        confident=result.confident,
        timings_ms=result.timings_ms,
        chunks=[
            {
                "label": h.chunk.citation_label,
                "fused_rank": h.fused_rank,
                "rerank_score": h.rerank_score,
                "via": h.via,
            }
            for h in result.chunks
        ],
    )
