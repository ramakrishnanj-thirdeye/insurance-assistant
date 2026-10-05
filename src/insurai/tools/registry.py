"""The tools spec 05 exposes, by name: bound in-process by the agent and registered on the MCP server.

run_analytics joins in M6 (spec 02).
"""

from collections.abc import Callable
from typing import Any

from insurai.tools.audit import analyze_claim, portfolio_audit
from insurai.tools.claims import get_claim, get_claim_documents, get_claim_interactions
from insurai.tools.customers import get_customer_summary
from insurai.tools.hospitals import check_hospital
from insurai.tools.knowledge import get_coverage, search_policy
from insurai.tools.policies import get_policy

TOOLS: dict[str, Callable[..., Any]] = {
    fn.__name__: fn
    for fn in (
        get_claim,
        get_claim_documents,
        get_policy,
        get_customer_summary,
        check_hospital,
        get_claim_interactions,
        search_policy,
        get_coverage,
        analyze_claim,
        portfolio_audit,
    )
}
