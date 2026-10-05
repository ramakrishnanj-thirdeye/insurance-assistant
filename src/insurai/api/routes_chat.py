"""POST /chat and /chat/resume (spec 09). Every 403/404/409 is raised before the SSE stream opens."""

from collections.abc import Collection
from typing import Annotated

from fastapi import APIRouter, Depends
from sse_starlette import EventSourceResponse

from insurai.agent.runner import apending_review, astream_resume, astream_turn
from insurai.agent.threads import ThreadBusy, ThreadStateChanged, ThreadStatus
from insurai.api.deps import ApiState, api_state, busy, owned_thread
from insurai.api.identity import Identity, ensure_matches, identity
from insurai.api.problems import ApiError
from insurai.api.schemas import ChatRequest, ResumeRequest
from insurai.api.streaming import run_stream
from insurai.rules.schemas import ReviewDecision
from insurai.tools.access import load_personas

router = APIRouter(tags=["chat"])

Ident = Annotated[Identity, Depends(identity)]
State = Annotated[ApiState, Depends(api_state)]


async def _review_pending(api: ApiState, thread_id: str) -> ApiError | None:
    summary = await apending_review(api.graph, thread_id)
    if summary is None:
        return None
    return ApiError(
        409, "REVIEW_PENDING", "Resume the pending review before sending a new message.", review=summary
    )


def _no_pending(thread_id: str) -> ApiError:
    return ApiError(409, "NO_PENDING_REVIEW", f"Thread {thread_id} is not waiting for a review.")


async def _start(api: ApiState, thread_id: str, allowed: Collection[ThreadStatus]) -> str:
    try:
        return await api.store.start_run(thread_id, allowed)
    except ThreadBusy as exc:
        raise busy(thread_id) from exc
    except ThreadStateChanged as exc:
        if exc.status == "awaiting_review" and (err := await _review_pending(api, thread_id)) is not None:
            raise err from exc
        raise _no_pending(thread_id) from exc


@router.post("/chat", summary="Ask a question; streams SSE events")
async def chat(body: ChatRequest, ident: Ident, api: State) -> EventSourceResponse:
    ensure_matches(ident, body.persona, body.principal_id)
    if body.thread_id is None:
        record = await api.store.create(ident.persona, ident.principal_id, body.message, body.source)
    else:
        record = await owned_thread(api.store, body.thread_id, ident)
        if record.status == "awaiting_review":
            if (err := await _review_pending(api, record.thread_id)) is not None:
                raise err
            await api.store.set_status(record.thread_id, "active")  # stale status: no interrupt to resume
    thread_id = record.thread_id
    token = await _start(api, thread_id, {"active"})
    if (err := await _review_pending(api, thread_id)) is not None:  # status said active, checkpoint disagrees
        await api.store.finish_run(thread_id, token, "awaiting_review")
        raise err
    run = astream_turn(api.graph, thread_id, body.message, ident.persona, ident.tool_principal)
    return EventSourceResponse(run_stream(api, thread_id, token, run))


@router.post("/chat/resume", summary="Resume a paused claim review; streams SSE events")
async def chat_resume(body: ResumeRequest, ident: Ident, api: State) -> EventSourceResponse:
    record = await owned_thread(api.store, body.thread_id, ident)
    if not load_personas()[ident.persona].can_resume_review:
        raise ApiError(403, "ACCESS_DENIED", f"Persona {ident.persona} cannot resume a claim review.")
    if record.status == "active":
        raise _no_pending(record.thread_id)
    token = await _start(api, record.thread_id, {"awaiting_review"})
    if await apending_review(api.graph, record.thread_id) is None:
        await api.store.finish_run(record.thread_id, token, "active")
        raise _no_pending(record.thread_id)
    decision = ReviewDecision(action=body.action, note=body.note)
    run = astream_resume(api.graph, record.thread_id, decision)
    return EventSourceResponse(run_stream(api, record.thread_id, token, run))
