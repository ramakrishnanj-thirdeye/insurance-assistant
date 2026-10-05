"""get_customer_summary (spec 05). Names are never unique: two or more matches give a Disambiguation."""

from typing import Any

from insurai.tools import access
from insurai.tools.base import fetch_all, fetch_one, tool
from insurai.tools.ids import not_found, validate_id
from insurai.tools.schemas import (
    AccessDenied,
    CustomerSummary,
    Disambiguation,
    Match,
    NotFound,
    ToolContext,
)
from insurai.tools.sources import sql_source

MAX_MATCHES = 10


@tool
def get_customer_summary(
    ctx: ToolContext, customer_id: str | None = None, name: str | None = None, city: str | None = None
) -> CustomerSummary | Disambiguation | NotFound | AccessDenied:
    """Customer profile with policy and claim counts, by customer ID or by name (and optional city).

    A customer persona sees only their own summary and cannot search by name.
    """
    if access.is_scoped(ctx):
        if name is not None or city is not None:
            return access.denied()
        customer_id = customer_id or ctx.principal_id
    if customer_id is not None:
        return _by_id(ctx, customer_id)
    if name and name.strip():
        return _by_name(ctx, name, city)
    return NotFound(entity="customer", message="Give a customer ID (like CUST139920) or a customer name.")


def _by_id(ctx: ToolContext, customer_id: str) -> CustomerSummary | NotFound | AccessDenied:
    if bad := validate_id("customer", customer_id):
        return bad
    row = fetch_one("SELECT * FROM gold.v_customer_360 WHERE customer_id = ?", [customer_id])
    if row is None:
        return not_found("customer", customer_id)
    if not access.can_see_owner(ctx, customer_id):
        return access.denied()
    return _summary(ctx, row)


def _by_name(ctx: ToolContext, name: str, city: str | None) -> CustomerSummary | Disambiguation | NotFound:
    sql = "SELECT * FROM gold.v_customer_360 WHERE lower(customer_name) = lower(trim(?))"
    params: list[Any] = [name]
    if city:
        sql += " AND lower(city) = lower(trim(?))"
        params.append(city)
    rows = fetch_all(sql + " ORDER BY customer_id", params)
    if not rows:
        where = f" in {city}" if city else ""
        return NotFound(entity="customer", message=f"No customer with that name{where}. Try the customer ID.")
    if len(rows) == 1:
        return _summary(ctx, rows[0])
    shown = rows[:MAX_MATCHES]
    return Disambiguation(
        entity="customer",
        total_matches=len(rows),
        matches=[
            Match(id=r["customer_id"], city=r["city"], age=r["age"], policies=r["policies_total"])
            for r in shown
        ],
        message=f"{len(rows)} customers share that name. Which customer ID do you mean?",
        sources=[sql_source("customers", r["customer_id"]) for r in shown],
    )


def _summary(ctx: ToolContext, row: dict[str, Any]) -> CustomerSummary:
    return CustomerSummary.model_validate(
        {**access.visible(ctx, row), "sources": [sql_source("customers", row["customer_id"])]}
    )


# Agent-side helpers (spec 06 product resolution and claim clarification). Not MCP tools: they read only
# the principal's own rows, so they need no persona gate beyond the scope check.


def own_products(ctx: ToolContext) -> list[str]:
    """Products of the customer's in-force policies, else of all their policies; [] for unscoped personas."""
    if not access.is_scoped(ctx) or ctx.principal_id is None:
        return []
    rows = fetch_all(
        """SELECT product_name, bool_or(effective_status = 'In Force') AS in_force
           FROM silver.policies WHERE customer_id = ? GROUP BY product_name ORDER BY product_name""",
        [ctx.principal_id],
    )
    in_force = [r["product_name"] for r in rows if r["in_force"]]
    return in_force or [r["product_name"] for r in rows]


def own_claims(ctx: ToolContext, limit: int = 10) -> list[str]:
    """The customer's claim IDs, newest first; [] for unscoped personas."""
    if not access.is_scoped(ctx) or ctx.principal_id is None:
        return []
    rows = fetch_all(
        "SELECT claim_id FROM silver.claims WHERE customer_id = ? ORDER BY claim_date DESC, claim_id LIMIT ?",
        [ctx.principal_id, limit],
    )
    return [r["claim_id"] for r in rows]
