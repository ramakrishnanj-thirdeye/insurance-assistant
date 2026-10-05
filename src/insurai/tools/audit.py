"""Claim-judgment tools (spec 05, built on spec 07): analyze_claim and portfolio_audit."""

from typing import Any

import duckdb
from pydantic import BaseModel

from insurai.rules.engine import portfolio_counts, read_ruleset
from insurai.rules.schemas import ClaimAssessment, PortfolioReport
from insurai.settings import get_settings
from insurai.tools.base import fetch_all, one_connection, tool
from insurai.tools.ids import validate_id
from insurai.tools.knowledge import _products, _unknown_product
from insurai.tools.schemas import AccessDenied, NotFound, ToolContext, ToolResult
from insurai.tools.sources import sql_source

MAX_SAMPLES = 50


class AuditSample(BaseModel):
    claim_id: str
    product_name: str
    claim_status: str
    failed_rules: list[str]
    flags: list[str]


class PortfolioAudit(ToolResult):
    flag: str | None
    product: str | None
    report: PortfolioReport
    samples: list[AuditSample]


@tool
def analyze_claim(
    ctx: ToolContext, claim_id: str, narrate: bool = False
) -> ClaimAssessment | NotFound | AccessDenied:
    """Deterministic claim assessment: rule results with evidence and citations, document checklist,
    consistency flags (staff only), next best actions; with narrate, cited clauses and a narrative too."""
    if bad := validate_id("claim", claim_id):
        return bad
    from insurai.agent.dossier import analyze  # the dossier imports the tool registry

    return analyze(ctx, claim_id, narrate=narrate)


@tool
def portfolio_audit(
    ctx: ToolContext, flag: str | None = None, product: str | None = None, limit: int = MAX_SAMPLES
) -> PortfolioAudit | NotFound | AccessDenied:
    """Leakage radar: fail counts per rule, consistency-flag counts and sample claims from gold.rule_results;
    filter by a flag (C1..C4, P1) or a rule ID (R01..R12, its fails) and by product."""
    ruleset = read_ruleset()
    rules = [r.id for r in ruleset.rules]
    flags = [f.id for f in [*ruleset.decision_consistency, *ruleset.insights]]
    if flag is not None and flag not in rules + flags:
        return NotFound(entity="flag", message=f"Unknown flag {flag!r}; expected one of {rules + flags}.")
    if product is not None:
        canonical = _products().get(product.strip().lower())
        if canonical is None:
            return _unknown_product(product)
        product = canonical
    limit = max(1, min(int(limit), MAX_SAMPLES))
    conditions, params = [], []
    if flag in rules:
        conditions.append(f"{flag} = 'fail'")
    elif flag is not None:
        conditions.append(flag)
    if product is not None:
        conditions.append("product_name = ?")
        params.append(product)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    try:
        with one_connection() as con:
            report = portfolio_counts(con, ruleset, product)
            rows = fetch_all(
                f"SELECT * FROM gold.rule_results {where} ORDER BY claim_id LIMIT ?", [*params, limit]
            )
    except duckdb.CatalogException:
        return NotFound(
            entity="rule_results", message="gold.rule_results is not built yet: run `make rules`."
        )
    samples = [_sample(r, rules, flags) for r in rows]
    sources = [sql_source("rule_results", s.claim_id) for s in samples] or [
        sql_source("rule_results", flag or rules[0])
    ]
    return PortfolioAudit(
        flag=flag,
        product=product,
        report=report.model_copy(update={"as_of": get_settings().as_of_date}),
        samples=samples,
        sources=sources,
    )


def _sample(row: dict[str, Any], rules: list[str], flags: list[str]) -> AuditSample:
    return AuditSample(
        claim_id=row["claim_id"],
        product_name=row["product_name"],
        claim_status=row["claim_status"],
        failed_rules=[r for r in rules if row.get(r) == "fail"],
        flags=[f for f in flags if row.get(f)],
    )
