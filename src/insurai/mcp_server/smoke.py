"""`make mcp-smoke` (AC-05-08): start the server over stdio, list the tools with their schemas, and check
that MCP results equal the in-process results.
"""

import asyncio
import os
import sys
from datetime import date
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from insurai.observability import get_logger
from insurai.settings import get_settings
from insurai.tools.registry import TOOLS
from insurai.tools.schemas import ToolContext

log = get_logger(__name__)

# (tool, args) compared over MCP and in-process; get_claim("CLM300210") is the spec's check
PROBES: list[tuple[str, dict[str, Any]]] = [
    ("get_claim", {"claim_id": "CLM300210"}),
    ("get_claim_documents", {"claim_id": "CLM300210"}),
    ("get_policy", {"policy_id": "POL218917"}),
    ("check_hospital", {"hospital_id": "HOSP1257"}),
    ("get_customer_summary", {"name": "Arjun Sharma"}),
    ("get_claim", {"claim_id": "CLM999999"}),
]


async def check_server(session: ClientSession, as_of: date) -> list[str]:
    """Problems found (empty = pass). The server must run as claims_agent."""
    problems: list[str] = []
    listed = {t.name: t for t in (await session.list_tools()).tools}
    if missing := set(TOOLS) - set(listed):
        problems.append(f"tools not listed: {sorted(missing)}")
    for name, t in listed.items():
        if not t.inputSchema.get("properties") and name in TOOLS:
            problems.append(f"{name}: empty input schema")
        if "ctx" in t.inputSchema.get("properties", {}):
            problems.append(f"{name}: ctx leaked into the input schema")
        if not t.outputSchema:
            problems.append(f"{name}: no output schema")

    ctx = ToolContext(persona="claims_agent", as_of=as_of, trace_id="mcp-smoke")
    for name, args in PROBES:
        result = await session.call_tool(name, args)
        over_mcp = (result.structuredContent or {}).get("result")
        in_process = TOOLS[name](ctx, **args).model_dump(mode="json")
        if result.isError or over_mcp != in_process:
            problems.append(f"{name}({args}): MCP result differs from in-process")
    return problems


async def _run() -> list[str]:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "insurai.mcp_server", "--transport", "stdio"],
        env={**os.environ, "INSURAI_PERSONA": "claims_agent", "PYTHONUTF8": "1"},
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        return await check_server(session, get_settings().as_of_date)


def main() -> int:
    problems = asyncio.run(_run())
    for p in problems:
        log.error("mcp-smoke: %s", p)
    if not problems:
        log.info(
            "mcp-smoke passed: %d tools listed with schemas, %d probes equal in-process",
            len(TOOLS),
            len(PROBES),
        )
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
