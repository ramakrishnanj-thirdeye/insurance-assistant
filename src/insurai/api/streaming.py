"""Runner events → SSE (spec 09 SSE events):

thread → (node | tool_start | tool | heartbeat | token | draft_hidden)… → interrupt | final → done;
on failure: error → done. A node running longer than `agent.heartbeat_s` gets a `heartbeat` every
`heartbeat_s` so the client can rotate its status line.

The lease taken before the stream opened is ended on every exit path (final, interrupt, error, client
disconnect): the status comes from the checkpoint, so a pending review is never lost.
"""

import asyncio
import contextlib
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from sse_starlette import ServerSentEvent

from insurai.agent.runner import RunEvent, apending_review
from insurai.agent.schemas import TurnResult
from insurai.api.deps import ApiState
from insurai.observability import get_logger
from insurai.settings import get_settings

log = get_logger(__name__)


def sse(event: str, data: dict[str, Any]) -> ServerSentEvent:
    return ServerSentEvent(event=event, data=json.dumps(data, ensure_ascii=False, default=str))


def final_payload(result: TurnResult) -> dict[str, Any]:
    return {
        "answer_markdown": result.answer_markdown,
        "citations": result.citations,
        "trace": [e.model_dump(mode="json") for e in result.trace],
        "assessment": result.assessment,
        "verified": bool(result.verification_passed),
        "analytics": result.analytics.model_dump(mode="json") if result.analytics else None,
    }


@dataclass
class _Running:
    name: str
    started: float
    beats: int = 0


_END = object()


async def with_heartbeats(run: AsyncIterator[RunEvent], interval_s: float) -> AsyncIterator[RunEvent]:
    """Pass `run` through, adding ("heartbeat", {node, elapsed_ms, beat}) every `interval_s` per running node.

    A pump task feeds a queue so waiting for the next beat never cancels the graph's own iterator; the
    pump is cancelled on every exit path (including a client disconnect).
    """
    queue: asyncio.Queue[Any] = asyncio.Queue()

    async def pump() -> None:
        try:
            async for item in run:
                await queue.put(item)
        except Exception as exc:
            await queue.put(exc)
        else:
            await queue.put(_END)

    task = asyncio.create_task(pump())
    running: list[_Running] = []
    try:
        while True:
            due = [r.started + (r.beats + 1) * interval_s for r in running]
            timeout = max(0.0, min(due) - time.perf_counter()) if due else None
            try:
                item = await asyncio.wait_for(queue.get(), timeout)
            except TimeoutError:
                now = time.perf_counter()
                for r in running:
                    beats = int((now - r.started) // interval_s)
                    if beats > r.beats:
                        r.beats = beats
                        elapsed = round((now - r.started) * 1000)
                        yield "heartbeat", {"node": r.name, "elapsed_ms": elapsed, "beat": beats}
                continue
            if item is _END:
                return
            if isinstance(item, Exception):
                raise item
            kind, data = item
            if kind == "node" and data.get("status") == "start":
                running.append(_Running(data["name"], time.perf_counter()))
            elif kind == "node":
                match = next((r for r in running if r.name == data["name"]), None)
                if match is not None:
                    running.remove(match)
            yield item
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def run_stream(
    api: ApiState, thread_id: str, token: str, run: AsyncIterator[RunEvent]
) -> AsyncIterator[ServerSentEvent]:
    yield sse("thread", {"thread_id": thread_id})
    answered = False
    try:
        async for kind, data in with_heartbeats(run, get_settings().agent.heartbeat_s):
            if kind != "result":
                yield sse(kind, data)
            elif data.interrupt is not None:
                yield sse("interrupt", {"assessment_summary": data.interrupt})
            else:
                answered = True
                yield sse("final", final_payload(data))
    except Exception:
        log.exception("thread %s: turn failed", thread_id)
        yield sse("error", {"code": "TURN_FAILED", "message": "The assistant could not finish this turn."})
    finally:
        await asyncio.shield(_finish(api, thread_id, token, answered))
    yield sse("done", {})


async def _finish(api: ApiState, thread_id: str, token: str, answered: bool) -> None:
    try:
        pending = await apending_review(api.graph, thread_id)
        snapshot = await api.graph.aget_state({"configurable": {"thread_id": thread_id}})
        status = "awaiting_review" if pending is not None else "active"
        entities = snapshot.values.get("active_entities")
        await api.store.finish_run(
            thread_id, token, status, entities, count_turn=answered and pending is None
        )
    except Exception:
        log.exception(
            "thread %s: could not end the running lease; it expires after turn_timeout_s", thread_id
        )
