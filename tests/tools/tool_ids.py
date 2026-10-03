"""Known IDs and a ToolContext factory shared by the tools and MCP tests."""

from datetime import date

from insurai.tools.schemas import Persona, ToolContext

KNOWN_CLAIM = "CLM300210"  # owned by CUST139920, policy POL218917, hospital HOSP1257
KNOWN_OWNER = "CUST139920"
KNOWN_POLICY = "POL218917"
KNOWN_HOSPITAL = "HOSP1257"


def make_ctx(persona: Persona = "claims_agent", principal_id: str | None = None) -> ToolContext:
    return ToolContext(persona=persona, principal_id=principal_id, as_of=date(2026, 10, 1), trace_id="test")
