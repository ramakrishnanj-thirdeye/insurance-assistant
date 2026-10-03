"""get_policy (spec 05): the policy schedule with effective_status, which replaces the stale policy_status."""

from insurai.tools import access
from insurai.tools.base import fetch_one, tool
from insurai.tools.ids import not_found, validate_id
from insurai.tools.schemas import AccessDenied, NotFound, PolicyView, ToolContext
from insurai.tools.sources import sql_source


@tool
def get_policy(ctx: ToolContext, policy_id: str) -> PolicyView | NotFound | AccessDenied:
    """Policy schedule: product, period, sum insured, premium, effective status and status conflict."""
    if bad := validate_id("policy", policy_id):
        return bad
    row = fetch_one("SELECT * FROM silver.policies WHERE policy_id = ?", [policy_id])
    if row is None:
        return not_found("policy", policy_id)
    if not access.can_see_owner(ctx, row["customer_id"]):
        return access.denied()
    return PolicyView.model_validate(
        {**access.visible(ctx, row), "sources": [sql_source("policies", policy_id)]}
    )
