"""Run one turn or resume a review on a thread (the entry points the API and evals use)."""

from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from insurai.agent.schemas import TurnResult
from insurai.guardrails.verify import labels_in
from insurai.rules.schemas import ReviewDecision
from insurai.tools.schemas import Persona


class ReviewPending(RuntimeError):
    """The thread is paused for a human review; resume it before sending a new message (spec 09: 409)."""

    def __init__(self, summary: dict[str, Any]) -> None:
        super().__init__(f"thread awaits review of {summary.get('claim_id')}")
        self.summary = summary


class NoPendingReview(RuntimeError):
    """resume() on a thread that is not waiting for a review (spec 09: 409 NO_PENDING_REVIEW)."""


def _config(thread_id: str, callbacks: list[BaseCallbackHandler] | None) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id}, "callbacks": list(callbacks or [])}


def pending_review(graph: CompiledStateGraph, thread_id: str) -> dict[str, Any] | None:
    snapshot = graph.get_state(_config(thread_id, None))
    return dict(snapshot.interrupts[0].value) if snapshot.interrupts else None


def run_turn(
    graph: CompiledStateGraph,
    thread_id: str,
    message: str,
    persona: Persona,
    principal_id: str | None = None,
    callbacks: list[BaseCallbackHandler] | None = None,
) -> TurnResult:
    if (summary := pending_review(graph, thread_id)) is not None:
        raise ReviewPending(summary)
    config = _config(thread_id, callbacks)
    graph.invoke(
        {"messages": [HumanMessage(content=message)], "persona": persona, "principal_id": principal_id},
        config,
    )
    return result(graph, thread_id)


def resume(
    graph: CompiledStateGraph,
    thread_id: str,
    decision: ReviewDecision,
    callbacks: list[BaseCallbackHandler] | None = None,
) -> TurnResult:
    if pending_review(graph, thread_id) is None:
        raise NoPendingReview(thread_id)
    graph.invoke(Command(resume=decision), _config(thread_id, callbacks))
    return result(graph, thread_id)


def result(graph: CompiledStateGraph, thread_id: str) -> TurnResult:
    snapshot = graph.get_state(_config(thread_id, None))
    values = snapshot.values
    assessment = values.get("assessment")
    verification = values.get("verification")
    common = {
        "thread_id": thread_id,
        "trace": values.get("trace", []),
        "assessment": assessment.model_dump(mode="json") if assessment is not None else None,
        "verification_passed": verification.passed if verification is not None else None,
    }
    if snapshot.interrupts:
        return TurnResult(
            answer_markdown="", citations=[], interrupt=dict(snapshot.interrupts[0].value), **common
        )
    last = values["messages"][-1]
    answer = str(last.content) if isinstance(last, AIMessage) else ""
    return TurnResult(answer_markdown=answer, citations=labels_in(answer), **common)
