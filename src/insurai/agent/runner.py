"""Run one turn or resume a review on a thread (the entry points the API and evals use).

Sync functions serve evals and tests (InMemorySaver, SqliteSaver); the `a*` variants serve the async API
(AsyncSqliteSaver cannot answer a sync get_state). `astream_turn` and `astream_resume` yield neutral
events the API maps to SSE (spec 09): ("node", {name, status, ms}), ("tool", {...}), then
("result", TurnResult).
"""

import time
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, StateSnapshot

from insurai.agent.schemas import TraceEvent, TurnResult
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
    return _pending(graph.get_state(_config(thread_id, None)))


async def apending_review(graph: CompiledStateGraph, thread_id: str) -> dict[str, Any] | None:
    return _pending(await graph.aget_state(_config(thread_id, None)))


def _pending(snapshot: StateSnapshot) -> dict[str, Any] | None:
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


RunEvent = tuple[str, Any]
NOT_OK = frozenset({"not_found", "access_denied"})


async def astream_turn(
    graph: CompiledStateGraph,
    thread_id: str,
    message: str,
    persona: Persona,
    principal_id: str | None = None,
    callbacks: list[BaseCallbackHandler] | None = None,
) -> AsyncIterator[RunEvent]:
    if (summary := await apending_review(graph, thread_id)) is not None:
        raise ReviewPending(summary)
    payload = {"messages": [HumanMessage(content=message)], "persona": persona, "principal_id": principal_id}
    async for item in _astream(graph, thread_id, payload, callbacks):
        yield item


async def astream_resume(
    graph: CompiledStateGraph,
    thread_id: str,
    decision: ReviewDecision,
    callbacks: list[BaseCallbackHandler] | None = None,
) -> AsyncIterator[RunEvent]:
    if await apending_review(graph, thread_id) is None:
        raise NoPendingReview(thread_id)
    async for item in _astream(graph, thread_id, Command(resume=decision), callbacks):
        yield item


async def _astream(
    graph: CompiledStateGraph, thread_id: str, payload: Any, callbacks: list[BaseCallbackHandler] | None
) -> AsyncIterator[RunEvent]:
    """Node start/end from stream mode `tasks`, tool calls from the workers' trace events in `updates`."""
    started: dict[str, float] = {}
    config = _config(thread_id, callbacks)
    async for mode, data in graph.astream(payload, config, stream_mode=["tasks", "updates"]):
        if mode == "tasks":
            if "result" not in data:
                started[data["id"]] = time.perf_counter()
                yield "node", {"name": data["name"], "status": "start"}
            else:
                ms = round((time.perf_counter() - started.pop(data["id"], time.perf_counter())) * 1000, 1)
                yield (
                    "node",
                    {
                        "name": data["name"],
                        "status": "end",
                        "ms": ms,
                        "interrupted": bool(data["interrupts"]),
                    },
                )
            continue
        for update in data.values():
            trace = update.get("trace") if isinstance(update, dict) else None
            for ev in trace if isinstance(trace, list) else []:
                if isinstance(ev, TraceEvent) and ev.kind == "tool":
                    yield "tool", tool_event(ev)
    yield "result", await aresult(graph, thread_id)


def tool_event(ev: TraceEvent) -> dict[str, Any]:
    return {
        "name": ev.name,
        "args_redacted": ev.data.get("args", {}),
        "ms": ev.duration_ms,
        "ok": ev.data.get("result_kind") not in NOT_OK,
    }


def result(graph: CompiledStateGraph, thread_id: str) -> TurnResult:
    return _from_snapshot(graph.get_state(_config(thread_id, None)), thread_id)


async def aresult(graph: CompiledStateGraph, thread_id: str) -> TurnResult:
    return _from_snapshot(await graph.aget_state(_config(thread_id, None)), thread_id)


def _from_snapshot(snapshot: StateSnapshot, thread_id: str) -> TurnResult:
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
