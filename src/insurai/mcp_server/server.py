"""FastMCP server exposing the spec 05 tools (ADR-005).

The persona is fixed per server process (env INSURAI_PERSONA, INSURAI_PRINCIPAL_ID); every call gets a fresh
ToolContext from `ctx_factory`. Tools run in a worker thread so a slow call does not block the event loop.
"""

import functools
import inspect
import os
import uuid
from collections.abc import Callable
from typing import Any, cast, get_args

import anyio
from mcp.server.fastmcp import FastMCP

from insurai.settings import get_settings
from insurai.tools.ids import validate_id
from insurai.tools.registry import TOOLS
from insurai.tools.schemas import Persona, ToolContext

INSTRUCTIONS = (
    "Insurance claims and policy tools over a read-only warehouse and the policy wordings. "
    "Every result carries `sources`; cite their labels. Facts come only from these results."
)

CtxFactory = Callable[[], ToolContext]


def build_server(ctx_factory: CtxFactory) -> FastMCP:
    s = get_settings().mcp
    server = FastMCP("insurai", instructions=INSTRUCTIONS, host=s.http_host, port=s.http_port)
    for name, fn in TOOLS.items():
        server.add_tool(
            _bind(fn, ctx_factory), name=name, description=inspect.getdoc(fn), structured_output=True
        )
    return server


def ctx_factory_from_env(env: dict[str, str] | None = None) -> CtxFactory:
    """Read the fixed identity once; raise ValueError for an unusable one."""
    env = dict(os.environ if env is None else env)
    raw = env.get("INSURAI_PERSONA", "claims_agent")
    if raw not in get_args(Persona):
        raise ValueError(f"INSURAI_PERSONA={raw!r}; expected one of {get_args(Persona)}")
    persona = cast(Persona, raw)
    principal = env.get("INSURAI_PRINCIPAL_ID") or None
    if persona == "customer" and (principal is None or validate_id("customer", principal)):
        raise ValueError(
            "INSURAI_PERSONA=customer needs INSURAI_PRINCIPAL_ID set to a customer ID (CUST######)"
        )
    as_of = get_settings().as_of_date

    def factory() -> ToolContext:
        return ToolContext(
            persona=persona, principal_id=principal, as_of=as_of, trace_id=f"mcp-{uuid.uuid4().hex[:12]}"
        )

    return factory


def _bind(fn: Callable[..., Any], ctx_factory: CtxFactory) -> Callable[..., Any]:
    """An async MCP handler with `fn`'s signature minus `ctx` (FastMCP derives the schemas from it)."""
    signature = inspect.signature(fn)

    @functools.wraps(fn)
    async def handler(**kwargs: Any) -> Any:
        return await anyio.to_thread.run_sync(functools.partial(fn, ctx_factory(), **kwargs))

    handler.__signature__ = signature.replace(  # type: ignore[attr-defined]
        parameters=[p for p in signature.parameters.values() if p.name != "ctx"]
    )
    return handler
