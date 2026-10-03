"""AC-05-08 over an in-memory MCP session; `make mcp-smoke` repeats the check over real stdio."""

import asyncio
from datetime import date
from typing import Any

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from insurai.mcp_server.server import build_server, ctx_factory_from_env
from insurai.mcp_server.smoke import check_server
from insurai.settings import get_settings
from insurai.tools.registry import TOOLS

AS_OF = date(2026, 10, 1)


def _call(env: dict[str, str], name: str, args: dict[str, Any]) -> Any:
    async def run() -> Any:
        server = build_server(ctx_factory_from_env(env))
        async with create_connected_server_and_client_session(server._mcp_server) as session:
            return await session.call_tool(name, args)

    return asyncio.run(run())


@pytest.fixture
def warehouse_built() -> None:
    if not get_settings().paths.warehouse.exists():
        pytest.skip("data/warehouse.duckdb not built: run `make data`")


@pytest.mark.integration
def test_AC_05_08_mcp_lists_tools_with_schemas_and_matches_inprocess(warehouse_built: None) -> None:
    async def run() -> tuple[list[str], set[str]]:
        server = build_server(ctx_factory_from_env({"INSURAI_PERSONA": "claims_agent"}))
        async with create_connected_server_and_client_session(server._mcp_server) as session:
            listed = {t.name for t in (await session.list_tools()).tools}
            return await check_server(session, AS_OF), listed

    problems, listed = asyncio.run(run())
    assert problems == []
    assert listed == set(TOOLS)


@pytest.mark.integration
def test_AC_05_08_mcp_get_claim_equals_inprocess(warehouse_built: None) -> None:
    from insurai.tools.schemas import ToolContext

    result = _call({"INSURAI_PERSONA": "claims_agent"}, "get_claim", {"claim_id": "CLM300210"})
    ctx = ToolContext(persona="claims_agent", as_of=AS_OF, trace_id="t")
    assert not result.isError
    assert result.structuredContent["result"] == TOOLS["get_claim"](ctx, claim_id="CLM300210").model_dump(
        mode="json"
    )
    assert result.structuredContent["result"]["claim_status"] == "Approved"


@pytest.mark.integration
def test_M3_mcp_persona_fixed_from_env(warehouse_built: None) -> None:
    owner = {"INSURAI_PERSONA": "customer", "INSURAI_PRINCIPAL_ID": "CUST139920"}
    other = {"INSURAI_PERSONA": "customer", "INSURAI_PRINCIPAL_ID": "CUST100000"}
    mine = _call(owner, "get_claim", {"claim_id": "CLM300210"}).structuredContent["result"]
    assert mine["claim_id"] == "CLM300210" and "fraud_risk_score" not in mine
    assert _call(other, "get_claim", {"claim_id": "CLM300210"}).structuredContent["result"]["kind"] == (
        "access_denied"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "env",
    [
        {"INSURAI_PERSONA": "admin"},
        {"INSURAI_PERSONA": "customer"},
        {"INSURAI_PERSONA": "customer", "INSURAI_PRINCIPAL_ID": "CLM300210"},
    ],
)
def test_M3_mcp_rejects_unusable_identity(env: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        ctx_factory_from_env(env)


@pytest.mark.unit
def test_M3_mcp_default_persona_is_claims_agent() -> None:
    assert ctx_factory_from_env({})().persona == "claims_agent"
