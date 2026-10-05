"""Live progress from inside a graph run (spec 09 `tool_start`): LangGraph's custom stream writer.

Outside a graph run (MCP server, scripts, tests calling tools directly) emitting does nothing. Only
status-safe arguments leave: record IDs that look like IDs and canonical product names. Free text the
user typed (queries, names, cities) never does.
"""

import re
from functools import lru_cache
from typing import Any

from insurai.observability import get_logger

log = get_logger(__name__)

ID_ARGS = {
    "claim_id": re.compile(r"CLM\d+"),
    "policy_id": re.compile(r"POL\d+"),
    "hospital_id": re.compile(r"HOSP\d+"),
}


@lru_cache(maxsize=1)
def _products() -> dict[str, str]:
    from insurai.knowledge import coverage  # lazy: the tool layer imports this module

    return {p.lower(): p for p in coverage.load_coverage(coverage.COVERAGE_FILE).products}


def status_args(args: dict[str, Any]) -> dict[str, str]:
    """The arguments a status line may show: well-formed IDs and canonical product names."""
    out: dict[str, str] = {}
    for key, pattern in ID_ARGS.items():
        value = args.get(key)
        if isinstance(value, str) and pattern.fullmatch(value.strip().upper()):
            out[key] = value.strip().upper()
    product = args.get("product")
    if isinstance(product, str) and (canonical := _products().get(product.strip().lower())):
        out["product"] = canonical
    return out


def emit_progress(event: str, data: dict[str, Any]) -> None:
    """Write `{"event": event, **data}` to the graph's custom stream; a no-op outside a graph run."""
    from langgraph.config import get_stream_writer

    try:
        writer = get_stream_writer()
    except (RuntimeError, KeyError):
        return
    try:
        writer({"event": event, **data})
    except Exception:  # progress is best effort; it must never fail a tool call
        log.debug("progress event %s dropped", event, exc_info=True)
