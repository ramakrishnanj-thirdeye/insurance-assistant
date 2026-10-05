"""claim_dossier subgraph (spec 06 node table; internals per spec 07 Behaviour 9).

gather_facts (get_claim, get_claim_documents, get_claim_interactions in parallel) → evaluate_rules (no LLM) →
fetch_clauses (the cited policy sections) → assemble (premise check) → review (interrupt: assess mode, needs
human review, persona ≠ customer) → narrate (LLM, assessment JSON only, completeness guard) → customer_draft
(template + small-model polish, no-guarantee check; full view only).

`analyze` is the same pipeline without the graph or interrupt (analyze_claim tool, GET /claims/{id}/dossier).
"""

import json
from typing import Annotated, Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from insurai.agent.prompts import load_prompt, template
from insurai.agent.schemas import Evidence, Intent, TraceEvent
from insurai.agent.state import WorkerInput, merge_evidence, merge_trace
from insurai.agent.trace import event, instant, llm_events, now_ms
from insurai.agent.workers import Recorder, retrieval_event, tool_context
from insurai.guardrails.verify import guarantee_hits, number_tokens, rewrite_guarantees
from insurai.llm.structured import text_call
from insurai.observability import get_logger
from insurai.retrieval.schemas import RetrievalResult, RetrievedChunk
from insurai.rules import engine
from insurai.rules.narrative import (
    complete_narrative,
    counts,
    findings,
    narrative_input,
    premise_correction,
    render_assessment,
)
from insurai.rules.schemas import ClaimAssessment, ReviewDecision
from insurai.settings import get_settings
from insurai.tools.registry import TOOLS
from insurai.tools.schemas import (
    AccessDenied,
    DocumentChecklist,
    InteractionHistory,
    NotFound,
    Persona,
    SourceRef,
    ToolContext,
)

log = get_logger(__name__)

WORKER = "claim_dossier"
CLAUSES_PER_CITATION = 1
NARRATE_INSTRUCTION = "Write the narrative for this assessment."
POLISH_INSTRUCTION = "Rewrite the draft."


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
    correction: str | None  # premise correction, internal to the subgraph


class DossierOutput(TypedDict, total=False):
    evidence: Annotated[list[Evidence], merge_evidence]
    trace: Annotated[list[TraceEvent], merge_trace]
    assessment: ClaimAssessment | None
    review: ReviewDecision | None


def _payload(state: DossierState) -> WorkerInput:
    return {k: state[k] for k in ("intent", "persona", "principal_id", "turn", "trace_id")}  # type: ignore[return-value]


# --- nodes ------------------------------------------------------------------------------------------------


def gather_facts(state: DossierState) -> dict[str, Any]:
    start = now_ms()
    rec = Recorder(_payload(state), WORKER)
    claim_id = rec.intent.entities.claim_id
    rec.call_parallel(
        [
            ("get_claim", {"claim_id": claim_id}),
            ("get_claim_documents", {"claim_id": claim_id}),
            ("get_claim_interactions", {"claim_id": claim_id}),
        ]
    )
    return rec.output(start)


def evaluate_rules(state: DossierState) -> dict[str, Any]:
    by_kind = {e.kind: e for e in state.get("evidence", [])}
    docs_ev, claim_ev = by_kind.get("DocumentChecklist"), by_kind.get("ClaimView")
    if docs_ev is None or claim_ev is None:
        return {}  # not found or denied: the tool evidence already says so
    docs = DocumentChecklist.model_validate({**docs_ev.payload, "sources": docs_ev.sources})
    inter_ev = by_kind.get("InteractionHistory")
    interactions = (
        InteractionHistory.model_validate({**inter_ev.payload, "sources": inter_ev.sources})
        if inter_ev
        else None
    )
    start = now_ms()
    result = engine.assess(tool_context(_payload(state)), docs, interactions)
    if not isinstance(result, ClaimAssessment):
        return {}
    turn, intent_id = state.get("turn", 0), state["intent"].id
    trace = [
        instant("rule", r.id, turn, intent_id=intent_id, status=r.status, severity=r.severity)
        for r in result.rules
    ]
    trace.append(event("node", "evaluate_rules", turn, start, intent_id=intent_id, rules=len(result.rules)))
    return {"assessment": result, "trace": trace}


def fetch_clauses(state: DossierState) -> dict[str, Any]:
    assessment = state.get("assessment")
    if assessment is None:
        return {}
    clauses, trace = clauses_for(tool_context(_payload(state)), assessment, state.get("turn", 0))
    return {"assessment": with_clauses(assessment, clauses), "trace": trace}


def assemble(state: DossierState) -> dict[str, Any]:
    assessment = state.get("assessment")
    if assessment is None:
        return {}
    intent = state["intent"]
    correction = premise_correction(
        intent.question, assessment.claim_id, assessment.facts.get("claim_status")
    )
    trace = []
    if correction:
        trace.append(instant("warning", "false_premise", state.get("turn", 0), correction=correction))
    return {"correction": correction, "trace": trace}


def review(state: DossierState) -> dict[str, Any]:
    assessment = state.get("assessment")
    if not should_interrupt(state["intent"], assessment, state["persona"]):
        return {}
    start = now_ms()
    decision = interrupt(review_summary(assessment))  # type: ignore[arg-type]  # resumed with a ReviewDecision
    decision = decision if isinstance(decision, ReviewDecision) else ReviewDecision.model_validate(decision)
    span = event("node", "human_review", state.get("turn", 0), start, action=decision.action)
    return {
        "review": decision,
        "assessment": assessment.model_copy(update={"review": decision}),  # type: ignore[union-attr]
        "trace": [span],
    }


def narrate(state: DossierState, config: RunnableConfig) -> dict[str, Any]:
    assessment = state.get("assessment")
    if assessment is None:
        return {}
    intent = state["intent"]
    correction = state.get("correction")
    start = now_ms()
    text, call = narrate_text(assessment, correction, intent.question or intent.sub_question, config)
    assessment = assessment.model_copy(update={"narrative": text})
    trace = llm_events(call, state.get("turn", 0), start) if call else []
    return {
        "assessment": assessment,
        "evidence": [assessment_evidence(assessment, correction, intent.id)],
        "trace": trace,
    }


def customer_draft(state: DossierState, config: RunnableConfig) -> dict[str, Any]:
    assessment = state.get("assessment")
    if assessment is None or assessment.view != "full":
        return {}
    start = now_ms()
    draft, call = customer_message(tool_context(_payload(state)), assessment, config)
    trace = llm_events(call, state.get("turn", 0), start) if call else []
    return {"assessment": assessment.model_copy(update={"customer_message_draft": draft}), "trace": trace}


# --- shared steps (graph and `analyze`) -------------------------------------------------------------------


def should_interrupt(intent: Intent, assessment: ClaimAssessment | None, persona: Persona) -> bool:
    """Pause only for an assessment (not an explanation) that needs review, never for a customer."""
    return (
        assessment is not None
        and intent.mode != "explain"
        and assessment.needs_human_review
        and persona != "customer"
    )


def review_summary(assessment: ClaimAssessment) -> dict[str, Any]:
    """The interrupt payload: what the reviewer's card shows (spec 10)."""
    return {
        "claim_id": assessment.claim_id,
        "claim_status": assessment.facts.get("claim_status"),
        "needs_human_review": assessment.needs_human_review,
        "counts": counts(assessment),
        "blockers": [
            r.message for r in findings(assessment) if r.status == "fail" and r.severity == "blocker"
        ],
        "escalation_reasons": assessment.escalation_reasons,
        "next_best_actions": assessment.next_best_actions,
        "missing_documents": assessment.checklist.missing,
        "pending_documents": assessment.checklist.pending,
    }


def clauses_for(
    ctx: ToolContext, assessment: ClaimAssessment, turn: int
) -> tuple[list[RetrievedChunk], list[TraceEvent]]:
    """The cited policy sections for every fail or review result: the product's coverage section, or the
    common (ALL) reimbursement or human-review section. A retrieval failure leaves no clauses."""
    wanted: dict[str, SourceRef] = {}
    for r in findings(assessment):
        if r.citation is not None and r.citation.kind == "policy":
            wanted.setdefault(r.citation.label, r.citation)
    product = assessment.facts.get("product_name")
    clauses: list[RetrievedChunk] = []
    trace: list[TraceEvent] = []
    for label, ref in wanted.items():
        start = now_ms()
        query = f"{assessment.facts.get('diagnosis_or_loss_type') or ''} {ref.section_name}".strip()
        try:
            result = TOOLS["search_policy"](ctx, query=query, product=product, section_hints=[ref.section_no])
        except Exception as exc:  # the index may be missing or locked by another process (spec 04)
            log.warning("fetch_clauses %s failed: %s", label, exc)
            trace.append(instant("warning", "fetch_clauses_failed", turn, label=label, error=str(exc)))
            continue
        kind = str(getattr(result, "kind", "ok"))
        trace.append(event("tool", "search_policy", turn, start, worker=WORKER, result_kind=kind))
        if not isinstance(result, RetrievalResult):
            continue
        trace.append(retrieval_event(result, turn, start, "dossier"))
        hits = [h for h in result.chunks if h.chunk.citation_label == label]
        clauses += hits[:CLAUSES_PER_CITATION]
    return clauses, trace


def with_clauses(assessment: ClaimAssessment, clauses: list[RetrievedChunk]) -> ClaimAssessment:
    sources = {s.label: s for s in assessment.sources}
    for c in clauses:
        ch = c.chunk
        sources.setdefault(
            ch.citation_label,
            SourceRef(
                kind="policy",
                label=ch.citation_label,
                product=ch.product,
                section_no=ch.section_no,
                section_name=ch.section_name,
            ),
        )
    return assessment.model_copy(update={"clauses": clauses, "sources": list(sources.values())})


def narrate_text(
    assessment: ClaimAssessment, correction: str | None, question: str, config: RunnableConfig | None
) -> tuple[str, Any]:
    """The LLM narrative with promises rewritten and the completeness guard applied; the deterministic
    rendering when the model returns nothing."""
    prompt = load_prompt("dossier_narrative")
    system = prompt.render(
        view=assessment.view,
        question=question,
        assessment_json=json.dumps(narrative_input(assessment, correction), ensure_ascii=False, default=str),
    )
    messages = [SystemMessage(system), HumanMessage(NARRATE_INSTRUCTION)]
    text, call = text_call("generator", messages, prompt.id, prompt.version, config)
    text = rewrite_guarantees(text).strip()
    if not text:
        return render_assessment(assessment, correction), call
    return complete_narrative(text, assessment, correction), call


def customer_message(
    ctx: ToolContext, assessment: ClaimAssessment, config: RunnableConfig | None
) -> tuple[str, Any]:
    """A message an agent can send: the customer-view next steps in the template, optionally polished by the
    small model. The polish is dropped if it promises anything or introduces a number the draft lacks."""
    customer_ctx = ctx.model_copy(update={"persona": "customer"})
    view = engine.assess(customer_ctx, assessment.checklist, assessment.interactions)
    steps = view.next_best_actions if isinstance(view, ClaimAssessment) else []
    draft = template(
        "customer_message",
        claim_id=assessment.claim_id,
        claim_status=assessment.facts.get("claim_status"),
        steps="; ".join(steps) or "none for now",
    )
    if not get_settings().agent.dossier_polish_customer_message:
        return draft, None
    prompt = load_prompt("customer_message")
    messages = [SystemMessage(prompt.render(draft=draft)), HumanMessage(POLISH_INSTRUCTION)]
    polished, call = text_call("small", messages, prompt.id, prompt.version, config)
    safe = (
        polished
        and not guarantee_hits(polished)
        and assessment.claim_id in polished
        and number_tokens(polished) <= number_tokens(draft)
    )
    return (polished if safe else draft), call


def assessment_evidence(assessment: ClaimAssessment, correction: str | None, intent_id: str) -> Evidence:
    """The dossier's evidence: the narrative input plus the narrative, cited by every label it uses."""
    n = counts(assessment)
    summary = (
        f"Claim {assessment.claim_id} assessment: {n['findings']} findings, {n['blockers']} blockers; "
        + ("needs human review" if assessment.needs_human_review else "no blocking findings")
        + "."
    )
    return Evidence(
        intent_id=intent_id,
        worker=WORKER,
        kind="ClaimAssessment",
        payload={
            **narrative_input(assessment, correction),
            "narrative": assessment.narrative,
            "checklist": {
                "missing": assessment.checklist.missing,
                "pending": assessment.checklist.pending,
                "rejected": assessment.checklist.rejected,
            },
        },
        sources=assessment.sources,
        summary=summary,
    )


def analyze(
    ctx: ToolContext, claim_id: str, narrate: bool = False, question: str | None = None
) -> ClaimAssessment | NotFound | AccessDenied:
    """The dossier without the graph or the interrupt: rules always; clauses, narrative and the customer
    message draft when `narrate`."""
    result = engine.evaluate_claim(
        claim_id, ctx.persona, principal_id=ctx.principal_id, trace_id=ctx.trace_id
    )
    if not isinstance(result, ClaimAssessment) or not narrate:
        return result
    clauses, _ = clauses_for(ctx, result, 0)
    assessment = with_clauses(result, clauses)
    correction = premise_correction(question, claim_id, assessment.facts.get("claim_status"))
    text, _ = narrate_text(assessment, correction, question or f"Assess claim {claim_id}.", None)
    assessment = assessment.model_copy(update={"narrative": text})
    if assessment.view == "full":
        draft, _ = customer_message(ctx, assessment, None)
        assessment = assessment.model_copy(update={"customer_message_draft": draft})
    return assessment


def build_dossier_graph(checkpointer: BaseCheckpointSaver | None = None) -> CompiledStateGraph:
    """The subgraph; a checkpointer only when it runs on its own (the claim_analysis eval)."""
    g = StateGraph(DossierState, input_schema=WorkerInput, output_schema=DossierOutput)
    for name, fn in (
        ("gather_facts", gather_facts),
        ("evaluate_rules", evaluate_rules),
        ("fetch_clauses", fetch_clauses),
        ("assemble", assemble),
        ("review", review),
        ("narrate", narrate),
        ("customer_draft", customer_draft),
    ):
        g.add_node(name, fn)  # type: ignore[call-overload]
    g.add_edge(START, "gather_facts")
    g.add_edge("gather_facts", "evaluate_rules")
    g.add_edge("evaluate_rules", "fetch_clauses")
    g.add_edge("fetch_clauses", "assemble")
    g.add_edge("assemble", "review")
    g.add_edge("review", "narrate")
    g.add_edge("narrate", "customer_draft")
    g.add_edge("customer_draft", END)
    return g.compile(checkpointer=checkpointer)
