"""Process-wide objects opened once at startup (spec 09 Behaviour) and the dependencies that reach them."""

from dataclasses import dataclass

from fastapi import Request
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from insurai.agent.threads import ThreadForbidden, ThreadNotFound, ThreadRecord, ThreadStore
from insurai.api.identity import Identity
from insurai.api.problems import ApiError


@dataclass
class ApiState:
    graph: CompiledStateGraph
    checkpointer: BaseCheckpointSaver
    store: ThreadStore


def api_state(request: Request) -> ApiState:
    return request.app.state.api  # type: ignore[no-any-return]


async def owned_thread(store: ThreadStore, thread_id: str, ident: Identity) -> ThreadRecord:
    """The thread if `ident` created it: 404 THREAD_NOT_FOUND, 403 THREAD_FORBIDDEN otherwise (reads too)."""
    try:
        return await store.authorize(thread_id, ident.persona, ident.principal_id)
    except ThreadNotFound as exc:
        raise ApiError(404, "THREAD_NOT_FOUND", f"No thread {thread_id}.") from exc
    except ThreadForbidden as exc:
        raise ApiError(403, "THREAD_FORBIDDEN", "This thread belongs to another identity.") from exc


def busy(thread_id: str) -> ApiError:
    return ApiError(409, "THREAD_BUSY", f"Thread {thread_id} is already running a turn; retry when it ends.")
