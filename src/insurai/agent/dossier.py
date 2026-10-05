"""claim_dossier subgraph (spec 06 node table; internals per spec 07 Behaviour 9).

PROVISIONAL until spec 07 (M5): `assess` derives needs_human_review from the ClaimView flags the warehouse
already computes, instead of the rules engine. gather_facts and the interrupt are the final shape.
"""

from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from insurai.agent.schemas import Evidence, Intent, TraceEvent
from insurai.agent.state import WorkerInput, merge_evidence, merge_trace
from insurai.agent.trace import event, instant, now_ms
from insurai.agent.workers import Recorder
from insurai.rules.schemas import ClaimAssessment, ReviewDecision, RuleResult
from insurai.settings import get_settings
from insurai.tools.registry import TOOLS
from insurai.tools.schemas import (
    AccessDenied,
    ClaimView,
    DocumentChecklist,
    InteractionHistory,
    NotFound,
    Persona,
    SourceRef,
    ToolContext,
)


class DossierState(TypedDict, total=False):
    intent: Intent
    persona: Persona
    principal_id: str | None
    turn: int
    trace_id: str
    evidence: Annotated[list[Evidence], merge_evidence]
    trace: Annotated[list[TraceEvent], merge_trace]
    assessment: ClaimAssessment | None
    review: ReviewDecision | None


class DossierOutput(TypedDict, total=False):
    evidence: Annotated[list[Evidence], merge_evidence]
    trace: Annotated[list[TraceEvent], merge_trace]
    assessment: ClaimAssessment | None
    review: ReviewDecision | None


def gather_facts(state: DossierState) -> dict[str, Any]:
    start = now_ms()
    payload: WorkerInput = {k: state[k] for k in ("intent", "persona", "principal_id", "turn", "trace_id")}  # type: ignore[misc]
    rec = Recorder(payload, "claim_dossier")
    claim_id = rec.intent.entities.claim_id
    for name in ("get_claim", "get_claim_documents", "get_claim_interactions"):
        rec.call(name, claim_id=claim_id)
    return rec.output(start)


def assess(state: DossierState) -> dict[str, Any]:
    by_kind = {e.kind: e for e in state.get("evidence", [])}
    claim_ev, docs_ev = by_kind.get("ClaimView"), by_kind.get("DocumentChecklist")
    if claim_ev is None or docs_ev is None:
        return {}  # not found or denied: the tool evidence already says so
    claim = ClaimView.model_validate({**claim_ev.payload, "sources": claim_ev.sources})
    docs = DocumentChecklist.model_validate({**docs_ev.payload, "sources": docs_ev.sources})
    inter_ev = by_kind.get("InteractionHistory")
    interactions = (
        InteractionHistory.model_validate({**inter_ev.payload, "sources": inter_ev.sources})
        if inter_ev
        else None
    )
    sources: list[SourceRef] = [*claim_ev.sources, *docs_ev.sources, *(inter_ev.sources if inter_ev else [])]
    assessment = build_assessment(claim, docs, interactions, sources, state["persona"])
    rules, needs_review = assessment.rules, assessment.needs_human_review
    turn = state.get("turn", 0)
    intent_id = state["intent"].id
    trace = [
        instant("rule", r.id, turn, intent_id=intent_id, status=r.status, severity=r.severity) for r in rules
    ]
    summary = (
        f"Claim {claim.claim_id} assessment: "
        + ("needs human review" if needs_review else "no blocking findings")
        + (f" ({'; '.join(assessment.escalation_reasons)})" if assessment.escalation_reasons else "")
        + "."
    )
    evidence = Evidence(
        intent_id=intent_id,
        worker="claim_dossier",
        kind="ClaimAssessment",
        payload={
            "claim_id": claim.claim_id,
            "needs_human_review": needs_review,
            "findings": [
                r.model_dump(mode="json", exclude={"citation"}) for r in rules if r.status != "pass"
            ],
        },
        sources=[claim_ev.sources[0]],
        summary=summary,
    )
    return {"assessment": assessment, "evidence": [evidence], "trace": trace}


def assess_claim(ctx: ToolContext, claim_id: str) -> ClaimAssessment | NotFound | AccessDenied:
    """The dossier without the graph or the interrupt (spec 09 GET /claims/{id}/dossier, narrate=false)."""
    claim = TOOLS["get_claim"](ctx, claim_id=claim_id)
    if not isinstance(claim, ClaimView):
        return claim
    docs = TOOLS["get_claim_documents"](ctx, claim_id=claim_id)
    if not isinstance(docs, DocumentChecklist):
        return docs
    found = TOOLS["get_claim_interactions"](ctx, claim_id=claim_id)
    interactions = found if isinstance(found, InteractionHistory) else None
    sources = [*claim.sources, *docs.sources, *(interactions.sources if interactions else [])]
    return build_assessment(claim, docs, interactions, sources, ctx.persona)


def build_assessment(
    claim: ClaimView,
    docs: DocumentChecklist,
    interactions: InteractionHistory | None,
    sources: list[SourceRef],
    persona: Persona,
) -> ClaimAssessment:
    rules = provisional_rules(claim, docs)
    needs_review = any(
        r.status == "review" or (r.status == "fail" and r.severity in ("blocker", "escalate")) for r in rules
    )
    return ClaimAssessment(
        claim_id=claim.claim_id,
        as_of=get_settings().as_of_date,
        view="customer" if persona == "customer" else "full",
        facts=claim.model_dump(mode="json", exclude={"sources"}),
        rules=rules,
        checklist=docs,
        needs_human_review=needs_review,
        escalation_reasons=[]
        if persona == "customer"
        else [r.message or r.name for r in rules if r.status != "pass"],
        interactions=interactions,
        sources=sources,
    )


def review(state: DossierState) -> dict[str, Any]:
    assessment = state.get("assessment")
    if assessment is None or not assessment.needs_human_review or state["persona"] == "customer":
        return {}
    start = now_ms()
    decision = interrupt(review_summary(assessment))  # resumed with Command(resume=ReviewDecision(...))
    decision = decision if isinstance(decision, ReviewDecision) else ReviewDecision.model_validate(decision)
    span = event("node", "human_review", state.get("turn", 0), start, action=decision.action)
    return {
        "review": decision,
        "assessment": assessment.model_copy(update={"review": decision}),
        "trace": [span],
    }


def review_summary(assessment: ClaimAssessment) -> dict[str, Any]:
    return {
        "claim_id": assessment.claim_id,
        "claim_status": assessment.facts.get("claim_status"),
        "needs_human_review": assessment.needs_human_review,
        "escalation_reasons": assessment.escalation_reasons,
        "missing_documents": assessment.checklist.missing,
        "pending_documents": assessment.checklist.pending,
    }


def provisional_rules(claim: ClaimView, docs: DocumentChecklist) -> list[RuleResult]:
    """A subset of config/rules.yaml evaluated from ClaimView flags; replaced by the spec 07 engine in M5."""
    thresholds = get_settings().thresholds

    def rule(
        rid: str, name: str, ok: bool | None, severity: str, message: str, review: bool = False
    ) -> RuleResult:
        status = "not_applicable" if ok is None else "pass" if ok else ("review" if review else "fail")
        return RuleResult(
            id=rid,
            name=name,
            status=status,
            severity=severity,
            message=None if ok else message,  # type: ignore[arg-type]
            evidence={},
            citation=None,
        )

    return [
        rule(
            "R01",
            "Policy in force on claim date",
            claim.in_policy_period,
            "blocker",
            f"Claim date {claim.claim_date} falls outside the policy period "
            f"{claim.policy_start_date} to {claim.policy_end_date}",
        ),
        rule(
            "R02",
            "Policy not cancelled",
            claim.policy_status != "Cancelled",
            "blocker",
            "The policy is marked Cancelled",
        ),
        rule(
            "R03",
            "Schedule waiting period completed",
            claim.within_schedule_waiting is not True if claim.waiting_period_days else None,
            "blocker",
            f"Claim made within the schedule's {claim.waiting_period_days}-day waiting period",
        ),
        rule(
            "R05",
            "Loss type covered by product",
            claim.coverage_status == "covered",
            "blocker",
            f"{claim.diagnosis_or_loss_type} is {claim.coverage_status} under {claim.product_name}",
            review=claim.coverage_status != "not_covered",
        ),
        rule(
            "R06",
            "Required documents present",
            not docs.missing,
            "blocker",
            f"Missing required documents: {', '.join(docs.missing)}",
        ),
        rule(
            "R07",
            "Required documents verified",
            not docs.pending and not docs.rejected,
            "blocker",
            f"Pending verification: {', '.join(docs.pending) or 'none'}; "
            f"rejected: {', '.join(docs.rejected) or 'none'}",
            review=not docs.rejected,
        ),
        rule(
            "R10",
            "Manual review flag",
            None if claim.manual_review_flag is None else claim.manual_review_flag != 1,
            "escalate",
            "Flagged for manual review",
        ),
        rule(
            "R11",
            "Fraud risk below threshold",
            None
            if claim.fraud_risk_score is None
            else claim.fraud_risk_score < thresholds.fraud_review_score,
            "escalate",
            "Fraud risk score at or above the review threshold",
        ),
    ]


def build_dossier_graph() -> CompiledStateGraph:
    g = StateGraph(DossierState, input_schema=WorkerInput, output_schema=DossierOutput)
    g.add_node("gather_facts", gather_facts)
    g.add_node("assess", assess)
    g.add_node("review", review)
    g.add_edge(START, "gather_facts")
    g.add_edge("gather_facts", "assess")
    g.add_edge("assess", "review")
    g.add_edge("review", END)
    return g.compile()
