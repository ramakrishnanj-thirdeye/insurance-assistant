"""What every tool shares: the persona gate, the tracing span and read-only parameterised queries."""

import functools
import inspect
import json
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

import duckdb
from pydantic import BaseModel

from insurai import db
from insurai.guardrails.pii import redact_for_logs
from insurai.observability import get_logger
from insurai.observability.progress import emit_progress, status_args
from insurai.observability.tracing import tool_span
from insurai.tools import access
from insurai.tools.schemas import ToolContext

log = get_logger(__name__)

PII_ARGS = frozenset({"name"})  # a customer or hospital name typed by the user; never traced or logged
REDACTED = "[REDACTED]"


def tool[**P, R: BaseModel](fn: Callable[P, R]) -> Callable[P, R]:
    """Gate on the persona's tool list, then trace the call (name, args minus PII, duration, size)."""
    name = fn.__name__
    signature = inspect.signature(fn)

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        bound = signature.bind(*args, **kwargs)
        ctx: ToolContext = bound.arguments["ctx"]
        safe_args = redact_args({k: v for k, v in bound.arguments.items() if k != "ctx"})
        attributes = {
            "tool.name": name,
            "tool.args": json.dumps(safe_args, default=str),
            "insurai.trace_id": ctx.trace_id,
            "insurai.persona": ctx.persona,
        }
        emit_progress("tool_start", {"name": name, "args_redacted": status_args(safe_args)})
        with tool_span(name, attributes) as span:
            start = time.perf_counter()
            result = fn(*args, **kwargs) if access.tool_allowed(ctx, name) else access.tool_denied(name)
            ms = round((time.perf_counter() - start) * 1000, 1)
            size = len(result.model_dump_json())
            kind = str(getattr(result, "kind", "ok"))
            span.set_attributes({"tool.duration_ms": ms, "tool.result_size": size, "tool.result_kind": kind})
        log.info(
            "tool %s trace=%s args=%s kind=%s ms=%.1f size=%d",
            name,
            ctx.trace_id,
            redact_for_logs(safe_args, ctx.persona),
            kind,
            ms,
            size,
        )
        return result  # type: ignore[return-value]

    return wrapper  # type: ignore[return-value]


def redact_args(args: dict[str, Any]) -> dict[str, Any]:
    return {k: (REDACTED if k in PII_ARGS and v is not None else v) for k, v in args.items()}


_SHARED: ContextVar[duckdb.DuckDBPyConnection | None] = ContextVar("insurai_shared_connection", default=None)


@contextmanager
def one_connection() -> Iterator[duckdb.DuckDBPyConnection]:
    """One read-only connection for every fetch in this scope (a sequential burst of tool queries, such as
    evaluate_claim). Single-threaded only: DuckDB connections are not shared across threads."""
    shared = _SHARED.get()
    if shared is not None:
        yield shared
        return
    with db.connect(read_only=True) as con:
        token = _SHARED.set(con)
        try:
            yield con
        finally:
            _SHARED.reset(token)


def fetch_all(sql: str, params: list[Any]) -> list[dict[str, Any]]:
    """Rows as dicts from a parameterised query on a read-only connection (shared inside one_connection)."""
    with one_connection() as con:
        cur = con.execute(sql, params)
        columns = [d[0] for d in cur.description]
        return [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]


def fetch_one(sql: str, params: list[Any]) -> dict[str, Any] | None:
    rows = fetch_all(sql, params)
    return rows[0] if rows else None
