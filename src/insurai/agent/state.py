"""Graph state (spec 06 State). Only `messages` and `active_entities` carry across turns; input_guard
resets everything else at the start of each turn (Per-turn reset).
"""

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from insurai.agent.schemas import AnswerDraft, Entities, Evidence, Intent, Plan, Reset, TraceEvent
from insurai.guardrails.schemas import GuardResult, VerificationReport
from insurai.rules.schemas import ClaimAssessment, ReviewDecision
from insurai.tools.schemas import Persona


def merge_evidence(left: list[Evidence] | None, right: list[Evidence] | Reset) -> list[Evidence]:
    return [] if isinstance(right, Reset) else (left or []) + right


def merge_trace(left: list[TraceEvent] | None, right: list[TraceEvent] | Reset) -> list[TraceEvent]:
    return [] if isinstance(right, Reset) else (left or []) + right


class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    persona: Persona
    principal_id: str | None
    active_entities: Entities  # carried across turns for follow-ups
    guard: GuardResult | None
    resolved: Entities | None  # entities resolve_context found in this message
    fast_path: bool
    refusal: str | None  # deterministic refusal text set before planning (ownership pre-check)
    plan: Plan | None
    evidence: Annotated[list[Evidence], merge_evidence]
    assessment: ClaimAssessment | None
    review: ReviewDecision | None
    draft: AnswerDraft | None
    verification: VerificationReport | None
    verdict: str | None  # verify outcome: pass | retry | abstain
    attempts: int
    trace: Annotated[list[TraceEvent], merge_trace]
    turn: int
    turn_started_ms: float
    guard_end_ms: float
    notes: list[str]  # deterministic notes appended to the answer (e.g. intents truncated)


class WorkerInput(TypedDict):
    """What a Send carries to a worker: one intent plus the caller's identity."""

    intent: Intent
    persona: Persona
    principal_id: str | None
    turn: int
    trace_id: str


def worker_payload(state: AgentState, intent: Intent, trace_id: str) -> dict[str, Any]:
    return {
        "intent": intent,
        "persona": state["persona"],
        "principal_id": state.get("principal_id"),
        "turn": state.get("turn", 0),
        "trace_id": trace_id,
    }
