"""Runner events → SSE (spec 09 SSE events):

thread → node… → tool → interrupt | final → done;  on failure: error → done.

The lease taken before the stream opened is ended on every exit path (final, interrupt, error, client
disconnect): the status comes from the checkpoint, so a pending review is never lost.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from sse_starlette import ServerSentEvent

from insurai.agent.runner import RunEvent, apending_review
from insurai.agent.schemas import TurnResult
from insurai.api.deps import ApiState
from insurai.observability import get_logger

log = get_logger(__name__)


def sse(event: str, data: dict[str, Any]) -> ServerSentEvent:
    return ServerSentEvent(event=event, data=json.dumps(data, ensure_ascii=False, default=str))


def final_payload(result: TurnResult) -> dict[str, Any]:
    return {
        "answer_markdown": result.answer_markdown,
        "citations": result.citations,
        "trace": [e.model_dump(mode="json") for e in result.trace],
        "assessment": result.assessment,
    }


async def run_stream(
    api: ApiState, thread_id: str, token: str, run: AsyncIterator[RunEvent]
) -> AsyncIterator[ServerSentEvent]:
    yield sse("thread", {"thread_id": thread_id})
    answered = False
    try:
        async for kind, data in run:
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
