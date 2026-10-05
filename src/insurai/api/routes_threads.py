"""Thread endpoints (spec 09, ADR-009): list, detail, rename, delete. Reads are ownership-checked too."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from langchain_core.messages import AIMessage, HumanMessage

from insurai.agent.runner import apending_review
from insurai.api.deps import ApiState, api_state, busy, owned_thread
from insurai.api.identity import Identity, identity
from insurai.api.schemas import ChatMessage, RenameRequest, ThreadDetail, ThreadSummary

router = APIRouter(prefix="/threads", tags=["threads"])

Ident = Annotated[Identity, Depends(identity)]
State = Annotated[ApiState, Depends(api_state)]


@router.get("", response_model=list[ThreadSummary], summary="The caller's threads, newest first")
async def list_threads(
    ident: Ident,
    api: State,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ThreadSummary]:
    records = await api.store.list(ident.persona, ident.principal_id, limit=limit, offset=offset)
    return [ThreadSummary.of(r) for r in records]


@router.get("/{thread_id}", response_model=ThreadDetail)
async def get_thread(thread_id: str, ident: Ident, api: State) -> ThreadDetail:
    record = await owned_thread(api.store, thread_id, ident)
    values = (await api.graph.aget_state({"configurable": {"thread_id": thread_id}})).values
    messages = [
        ChatMessage(role="user" if isinstance(m, HumanMessage) else "assistant", content=str(m.content))
        for m in values.get("messages", [])
        if isinstance(m, HumanMessage | AIMessage)
    ]
    return ThreadDetail(
        **ThreadSummary.of(record).model_dump(),
        messages=messages,
        last_trace=values.get("trace", []),
        pending_review=await apending_review(api.graph, thread_id),
    )


@router.patch("/{thread_id}", response_model=ThreadSummary)
async def rename_thread(thread_id: str, body: RenameRequest, ident: Ident, api: State) -> ThreadSummary:
    await owned_thread(api.store, thread_id, ident)
    await api.store.rename(thread_id, body.title)
    return ThreadSummary.of(await api.store.get(thread_id))


@router.delete("/{thread_id}", status_code=204, response_class=Response)
async def delete_thread(thread_id: str, ident: Ident, api: State) -> Response:
    record = await owned_thread(api.store, thread_id, ident)
    if record.status == "running":
        raise busy(thread_id)
    await api.store.delete(thread_id)
    return Response(status_code=204)
