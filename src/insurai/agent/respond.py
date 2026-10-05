"""respond (spec 06): the final message, deterministic additions, active_entities update, total latency."""

from typing import Any

from langchain_core.messages import AIMessage

from insurai.agent.prompts import template
from insurai.agent.schemas import NO_WORKER, Entities, Evidence, TraceEvent
from insurai.agent.state import AgentState
from insurai.agent.trace import now_ms
from insurai.guardrails.verify import NO_RESULT_KINDS
from insurai.tools.messages import refusal

ENTITY_FROM_PAYLOAD = {
    "ClaimView": {
        "claim_id": "claim_id",
        "policy_id": "policy_id",
        "product_name": "product",
        "policy_type": "policy_type",
        "customer_id": "customer_id",
    },
    "PolicyView": {
        "policy_id": "policy_id",
        "product_name": "product",
        "policy_type": "policy_type",
        "customer_id": "customer_id",
    },
    "DocumentChecklist": {"claim_id": "claim_id"},
    "InteractionHistory": {"claim_id": "claim_id"},
    "HospitalCheck": {"hospital_id": "hospital_id"},
    "CustomerSummary": {"customer_id": "customer_id"},
}
_CLAIM_DEPENDENT = ("policy_id", "product", "policy_type", "hospital_id")


def respond(state: AgentState) -> dict[str, Any]:
    text = final_text(state)
    active = next_active_entities(state)
    total = TraceEvent(
        kind="total",
        name="turn",
        turn=state.get("turn", 0),
        start_ms=state.get("turn_started_ms") or now_ms(),
        end_ms=now_ms(),
        data={"answered_by": answered_by(state)},
    )
    guard = state.get("guard")
    blocked = [guard_event(state)] if guard is not None and not guard.allowed else []
    return {"messages": [AIMessage(content=text)], "active_entities": active, "trace": [*blocked, total]}


def guard_event(state: AgentState) -> TraceEvent:
    """The input_guard span, recorded by the node after it (input_guard itself returns trace=Reset())."""
    guard = state.get("guard")
    start = state.get("turn_started_ms") or now_ms()
    return TraceEvent(
        kind="node",
        name="input_guard",
        turn=state.get("turn", 0),
        start_ms=start,
        end_ms=state.get("guard_end_ms") or start,
        data={
            "allowed": guard.allowed if guard else True,
            "code": guard.code if guard else None,
            "pii_found": guard.pii_found if guard else [],
        },
    )


def answered_by(state: AgentState) -> str:
    guard = state.get("guard")
    if guard is not None and not guard.allowed:
        return f"guard:{guard.code}"
    if state.get("refusal"):
        return "refusal"
    plan = state.get("plan")
    if plan is not None and plan.clarification:
        return "clarification"
    return "draft" if state.get("draft") else "template"


def final_text(state: AgentState) -> str:
    guard = state.get("guard")
    if guard is not None and not guard.allowed and guard.code:
        return refusal(guard.code)
    if state.get("refusal"):
        return str(state["refusal"])
    plan = state.get("plan")
    if plan is not None and plan.clarification:
        return plan.clarification
    parts: list[str] = []
    draft = state.get("draft")
    if draft is not None:
        parts.append(draft.answer_markdown)
    elif plan is not None:
        types = {i.type for i in plan.intents}
        if "out_of_scope" in types:
            parts.append(refusal("OUT_OF_SCOPE"))
        elif types <= NO_WORKER:
            parts.append(template("greeting"))
    if decision := state.get("review"):
        parts.append(template("review_decision", action=decision.action, note=decision.note or "(none)"))
    assessment = state.get("assessment")
    if assessment is not None and assessment.needs_human_review and state.get("persona") == "customer":
        parts.append(template("specialist_review_customer"))
    parts.extend(state.get("notes") or [])
    return "\n\n".join(p for p in parts if p)


def next_active_entities(state: AgentState) -> Entities:
    """Carry entities to the next turn: a new claim replaces the old one and the IDs that hang off it."""
    active = state.get("active_entities") or Entities()
    resolved = state.get("resolved") or Entities()
    found = entities_from_evidence(state.get("evidence", []))
    stated = resolved.set_fields()
    plan = state.get("plan")
    if plan is not None:
        for intent in plan.intents:
            stated = {**intent.entities.set_fields(), **stated}
    if "claim_id" in found and found["claim_id"] != active.claim_id:
        active = active.model_copy(update=dict.fromkeys(_CLAIM_DEPENDENT))
    ok_ids = {k: v for k, v in stated.items() if k in ("product", "policy_type") or v in found.values()}
    return active.model_copy(update={**ok_ids, **found})


def entities_from_evidence(evidence: list[Evidence]) -> dict[str, str]:
    found: dict[str, str] = {}
    for ev in evidence:
        if ev.kind in NO_RESULT_KINDS:
            continue
        for src, dst in ENTITY_FROM_PAYLOAD.get(ev.kind, {}).items():
            if (value := ev.payload.get(src)) is not None and dst not in found:
                found[dst] = str(value)
    return found
