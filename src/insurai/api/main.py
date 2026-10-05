"""The FastAPI app (spec 09). `make api` runs `uvicorn insurai.api.main:app`.

Startup opens the async checkpointer and the thread store on `paths.checkpoints`, compiles the graph once,
and recovers threads left running. Single worker only: the per-thread lock is in-process (ADR-009).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from insurai.agent.checkpoint import async_sqlite_saver
from insurai.agent.graph import build_graph
from insurai.agent.runner import apending_review
from insurai.agent.threads import ThreadStore
from insurai.api import problems, routes_chat, routes_data, routes_threads
from insurai.api.deps import ApiState
from insurai.observability import get_logger
from insurai.retrieval import search
from insurai.settings import get_settings

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    path = get_settings().paths.checkpoints
    async with async_sqlite_saver(path) as saver:
        await saver.setup()
        graph = build_graph(saver)

        async def has_pending_review(thread_id: str) -> bool:
            return await apending_review(graph, thread_id) is not None

        async with ThreadStore.open(path, saver, has_pending_review) as store:
            recovered = await store.recover()
            if recovered:
                log.warning("reset %d thread(s) left running by the previous API process", recovered)
            app.state.api = ApiState(graph=graph, checkpointer=saver, store=store)
            try:
                yield
            finally:
                search.close_readers()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Insurance Claims & Policy Intelligence Assistant",
        version="0.1.0",
        description="API over the agent graph and tools (spec 09). Identity: X-Persona, X-Principal-Id.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().api.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    problems.install(app)
    app.include_router(routes_chat.router)
    app.include_router(routes_threads.router)
    app.include_router(routes_data.router)
    return app


app = create_app()
