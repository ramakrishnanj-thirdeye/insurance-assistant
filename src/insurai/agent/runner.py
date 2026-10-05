"""Run one turn or resume a review on a thread (the entry points the API and evals use).

Sync functions serve evals and tests (InMemorySaver, SqliteSaver); the `a*` variants serve the async API
(AsyncSqliteSaver cannot answer a sync get_state). `astream_turn` and `astream_resume` yield neutral
events the API maps to SSE (spec 09): ("node", {name, status, ms, ...}), ("tool_start", {...}),
("tool", {...}), ("token", {text, attempt}), ("draft_hidden", {attempt, reason}), then ("result", TurnResult).
"""

import time
from collections.abc import AsyncIterator
from typing import Any, cast

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, StateSnapshot

from insurai.agent.progress import DraftGate, plan_summary
from insurai.agent.schemas import Plan, TraceEvent, TurnResult
from insurai.agent.synthesize import narrative_is_answer
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


STREAM_MODES = ["tasks", "updates", "messages", "custom"]
TOKEN_NODE = "synthesize"
DOSSIER_NODE = "claim_dossier"
NARRATE_NODE = "narrate"  # inside claim_dossier; its tokens are the answer on claim-analysis turns (spec 06)


async def _plan(graph: CompiledStateGraph, thread_id: str) -> Plan | None:
    """The turn's plan from the checkpoint (a resumed review streams without the planner)."""
    plan = (await graph.aget_state(_config(thread_id, None))).values.get("plan")
    return plan if isinstance(plan, Plan) else None


async def _astream(
    graph: CompiledStateGraph, thread_id: str, payload: Any, callbacks: list[BaseCallbackHandler] | None
) -> AsyncIterator[RunEvent]:
    """Node start/end from `tasks`, tool calls from the workers' trace events in `updates`, tool starts from
    `custom`, and answer tokens from `messages` through a draft gate per attempt: synthesize's, or the
    dossier's narrate node when the narrative is the answer (one attempt counter for both)."""
    started: dict[str, float] = {}
    attempt = 0
    gate: DraftGate | None = None
    narrative_gate: DraftGate | None = None
    plan: Plan | None = None
    narrative_streams: bool | None = None  # decided at the first narrate token, from the turn's plan
    config = _config(thread_id, callbacks)
    # subgraphs=True: the dossier's LLM tokens only stream with it. Node, tool and update events are still
    # taken from the root namespace only, so clients see the same node sequence as before.
    async for part in graph.astream(payload, config, stream_mode=STREAM_MODES, subgraphs=True):  # type: ignore[arg-type]
        ns, mode, data = cast(tuple[tuple[str, ...], str, Any], part)
        in_dossier = bool(ns) and str(ns[0]).startswith(DOSSIER_NODE + ":")
        if mode == "messages":
            chunk, meta = data
            if not isinstance(chunk, AIMessageChunk):
                continue
            node = meta.get("langgraph_node")
            if node == TOKEN_NODE and not ns and gate is not None:
                for item in gate.feed(chunk.text):
                    yield item
            elif node == NARRATE_NODE and in_dossier:
                if narrative_streams is None:
                    plan = plan or await _plan(graph, thread_id)
                    narrative_streams = narrative_is_answer(plan)
                if not narrative_streams:
                    continue
                if narrative_gate is None:
                    attempt += 1
                    narrative_gate = DraftGate(attempt)
                for item in narrative_gate.feed(chunk.text):
                    yield item
            elif narrative_gate is not None and in_dossier:  # the next dossier node's LLM call
                for item in narrative_gate.close():
                    yield item
                narrative_gate = None
        elif mode == "custom":
            if isinstance(data, dict) and data.get("event") == "tool_start":
                yield "tool_start", {"name": data.get("name"), "args_redacted": data.get("args_redacted", {})}
        elif ns:
            continue  # subgraph tasks and updates: the root reports the dossier as one node
        elif mode == "tasks":
            if "result" not in data:
                started[data["id"]] = time.perf_counter()
                if data["name"] == TOKEN_NODE:
                    attempt += 1
                    gate = DraftGate(attempt)
                yield "node", {"name": data["name"], "status": "start"}
                continue
            if data["name"] == TOKEN_NODE and gate is not None:
                for item in gate.close():
                    yield item
                gate = None
            if data["name"] == DOSSIER_NODE and narrative_gate is not None:
                for item in narrative_gate.close():
                    yield item
                narrative_gate = None
            if data["name"] == "planner" and isinstance(data.get("result"), dict):
                found = data["result"].get("plan")
                plan = found if isinstance(found, Plan) else plan
            ms = round((time.perf_counter() - started.pop(data["id"], time.perf_counter())) * 1000, 1)
            end = {"name": data["name"], "status": "end", "ms": ms, "interrupted": bool(data["interrupts"])}
            yield "node", {**end, **node_extras(data["name"], data.get("result"))}
        else:
            for update in data.values():
                trace = update.get("trace") if isinstance(update, dict) else None
                for ev in trace if isinstance(trace, list) else []:
                    if isinstance(ev, TraceEvent) and ev.kind == "tool":
                        yield "tool", tool_event(ev)
    yield "result", await aresult(graph, thread_id)


def node_extras(name: str, result: Any) -> dict[str, Any]:
    """Safe extras on a node's end event: the verify outcome, the plan summary (spec 09)."""
    writes = result if isinstance(result, dict) else {}
    if name == "verify" and writes.get("verdict"):
        return {"outcome": writes["verdict"]}
    if name == "planner" or (name == "resolve_context" and writes.get("fast_path")):
        plan = writes.get("plan")
        return {"plan": plan_summary(plan)} if isinstance(plan, Plan) else {}
    return {}


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
