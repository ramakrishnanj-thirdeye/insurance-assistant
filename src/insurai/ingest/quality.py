"""Data-quality checks (spec 01 §Behaviour 5).

Integrity checks fail the build. Anomaly metrics never do: they are reported and feed the leakage radar
(ADR-007).
Every check is a named SQL query over bronze (raw as delivered) or silver/ref; table names are code constants.
"""

from dataclasses import dataclass
from typing import Literal

import duckdb

from insurai.ingest.schemas import AnomalyMetric, DataQualityReport, IntegrityCheck


@dataclass(frozen=True)
class Check:
    name: str
    description: str
    sql: str  # returns one integer: the number of failing rows


@dataclass(frozen=True)
class Metric:
    name: str
    description: str
    sql: str
    kind: Literal["int", "float", "bands"] = "int"  # bands: rows of (label, value)


def _pk(table: str, *cols: str) -> Check:
    key = ", ".join(cols)
    nulls = " OR ".join(f"{c} IS NULL" for c in cols)
    return Check(
        f"pk_{table}",
        f"bronze.{table} primary key ({key}) is unique and not null",
        f"SELECT count(*) - count(DISTINCT ({key})) + count(*) FILTER (WHERE {nulls}) FROM bronze.{table}",
    )


def _fk(child: str, col: str, parent: str, parent_col: str) -> Check:
    return Check(
        f"fk_{child}_{parent}",
        f"every non-null bronze.{child}.{col} exists in bronze.{parent}.{parent_col}",
        f"SELECT count(*) FROM bronze.{child} c WHERE c.{col} IS NOT NULL "
        f"AND NOT EXISTS (SELECT 1 FROM bronze.{parent} p WHERE p.{parent_col} = c.{col})",
    )


INTEGRITY_CHECKS: tuple[Check, ...] = (
    _pk("customers", "customer_id"),
    _pk("policies", "policy_id"),
    _pk("claims", "claim_id"),
    _pk("hospitals", "hospital_id"),
    _pk("customer_interactions", "interaction_id"),
    _pk("claim_documents", "claim_id", "document_type"),
    _fk("claims", "policy_id", "policies", "policy_id"),
    _fk("claims", "customer_id", "customers", "customer_id"),
    _fk("claims", "hospital_id", "hospitals", "hospital_id"),
    _fk("claim_documents", "claim_id", "claims", "claim_id"),
    _fk("customer_interactions", "claim_id", "claims", "claim_id"),
    # The raw logged customer must exist even though ownership comes from the claim (ADR-008).
    _fk("customer_interactions", "customer_id", "customers", "customer_id"),
    _fk("policies", "customer_id", "customers", "customer_id"),
    Check(
        "claim_customer_matches_policy_holder",
        "every claim's customer_id equals its policy's customer_id",
        "SELECT count(*) FROM bronze.claims c JOIN bronze.policies p USING (policy_id) "
        "WHERE c.customer_id IS DISTINCT FROM p.customer_id",
    ),
    Check(
        "claim_policy_type_matches_policy",
        "every claim's policy_type equals its policy's policy_type",
        "SELECT count(*) FROM bronze.claims c JOIN bronze.policies p USING (policy_id) "
        "WHERE c.policy_type IS DISTINCT FROM p.policy_type",
    ),
    Check(
        "claim_has_coverage_cell",
        "every claim's (product_name, diagnosis_or_loss_type) has a ref.diagnosis_coverage row",
        "SELECT count(*) FROM bronze.claims c JOIN bronze.policies p USING (policy_id) "
        "WHERE NOT EXISTS (SELECT 1 FROM ref.diagnosis_coverage d "
        "WHERE d.product_name = p.product_name AND d.diagnosis = c.diagnosis_or_loss_type)",
    ),
)

# Fixed bands for the fraud-signal metric; the top band absorbs the few scores >= 0.8.
FRAUD_BAND_EDGES: tuple[float, ...] = (0.0, 0.2, 0.4, 0.6, 1.0)


def _band_case(column: str) -> str:
    edges = FRAUD_BAND_EDGES
    whens = " ".join(
        f"WHEN {column} < {hi} THEN '{lo:.1f}-{hi:.1f}'" for lo, hi in zip(edges[:-1], edges[1:], strict=True)
    )
    return f"CASE {whens} ELSE '{edges[-2]:.1f}-{edges[-1]:.1f}' END"


def _count(where: str, table: str = "silver.policies") -> str:
    return f"SELECT count(*) FILTER (WHERE {where}) FROM {table}"


ANOMALY_METRICS: tuple[Metric, ...] = (
    Metric("claims_total", "claims in the warehouse", "SELECT count(*) FROM silver.claims"),
    Metric(
        "claims_in_policy_period",
        "claims dated inside their policy's start..end dates",
        _count("in_policy_period", "silver.claims"),
    ),
    Metric(
        "claims_before_policy_start",
        "claims dated before their policy started",
        _count("days_since_policy_start < 0", "silver.claims"),
    ),
    Metric(
        "claims_after_policy_end",
        "claims dated after their policy ended",
        "SELECT count(*) FROM silver.claims c JOIN silver.policies p USING (policy_id) "
        "WHERE c.claim_date > p.policy_end_date",
    ),
    Metric(
        "policies_in_force", "policies In Force at the as-of date", _count("effective_status = 'In Force'")
    ),
    Metric(
        "policies_lapsed",
        "policies whose end date is before the as-of date",
        _count("effective_status = 'Lapsed'"),
    ),
    Metric("policies_cancelled", "policies recorded Cancelled", _count("effective_status = 'Cancelled'")),
    Metric(
        "policies_not_started",
        "policies starting after the as-of date",
        _count("effective_status = 'Not Started'"),
    ),
    Metric(
        "policies_active_not_in_force",
        "policies recorded Active that are not In Force at the as-of date (stale policy_status)",
        _count("policy_status = 'Active' AND effective_status <> 'In Force'"),
    ),
    Metric(
        "policies_status_conflict",
        "policies whose recorded status contradicts effective_status "
        "(Active not In Force, or Expired In Force)",
        _count("status_conflict"),
    ),
    Metric(
        "interactions_total", "customer interactions", "SELECT count(*) FROM silver.customer_interactions"
    ),
    Metric(
        "interactions_logged_customer_not_owner",
        "interactions whose logged customer_id differs from the claim owner (ADR-008)",
        _count("logged_customer_id <> claim_owner_id", "silver.customer_interactions"),
    ),
    Metric(
        "interactions_before_claim_date",
        "interactions dated before the claim they refer to",
        _count("before_claim_date", "silver.customer_interactions"),
    ),
    Metric(
        "policies_extending_chain",
        "policies extending a continuous chain (continuous_cover_start earlier than their own start)",
        _count("continuous_cover_start < policy_start_date"),
    ),
    Metric(
        "policies_in_multi_policy_chain",
        "policies in a continuous chain of two or more policies of the same customer and product",
        "SELECT count(*) FILTER (WHERE n > 1) FROM (SELECT count(*) OVER "
        "(PARTITION BY customer_id, product_name, continuous_cover_start) AS n FROM silver.policies)",
    ),
    Metric(
        "policies_back_to_back_renewal",
        "policies starting on the previous policy's end date or the day after "
        "(strictly back-to-back renewals)",
        "SELECT count(*) FILTER (WHERE policy_start_date - prev_end IN (0, 1)) "
        "FROM (SELECT policy_start_date, lag(policy_end_date) OVER "
        "(PARTITION BY customer_id, product_name ORDER BY policy_start_date, policy_id) AS prev_end "
        "FROM silver.policies)",
    ),
    Metric(
        "policies_schedule_waiting_730_plus",
        "policies with a schedule waiting period of 730+ days on a 365-day policy "
        "(their claims can never clear R03)",
        _count("waiting_period_days >= 730"),
    ),
    Metric(
        "policies_schedule_waiting_730_plus_share",
        "share of policies with a schedule waiting period of 730+ days",
        "SELECT avg(CASE WHEN waiting_period_days >= 730 THEN 1.0 ELSE 0.0 END) FROM silver.policies",
        "float",
    ),
    Metric(
        "approved_claims_with_missing_upload",
        "Approved claims with at least one document upload_status = Missing (raw, any document type)",
        "SELECT count(DISTINCT c.claim_id) FROM silver.claims c "
        "JOIN silver.claim_documents d USING (claim_id) "
        "WHERE c.claim_status = 'Approved' AND d.upload_status = 'Missing'",
    ),
    Metric(
        "fraud_review_rate_by_score_band",
        "manual-review rate (%) per fraud_risk_score band; flat rates mean the score carries no signal",
        f"SELECT {_band_case('fraud_risk_score')} AS band, 100.0 * avg(manual_review_flag) "
        "FROM silver.claims GROUP BY band ORDER BY band",
        "bands",
    ),
    Metric(
        "claim_amount_p95",
        "95th percentile of claim_amount (thresholds.high_value_inr should match it)",
        "SELECT quantile_cont(claim_amount, 0.95) FROM silver.claims",
        "float",
    ),
    Metric(
        "high_value_claims",
        "claims above thresholds.high_value_inr",
        _count("high_value", "silver.claims"),
    ),
)

# Gold objects fingerprinted for rebuild determinism (AC-01-09), with their sort keys.
GOLD_KEYS: dict[str, str] = {
    "gold.claim_doc_checklist": "claim_id, document_type",
    "gold.claim_facts": "claim_id",
    "gold.v_claim_360": "claim_id",
    "gold.v_customer_360": "customer_id",
}


def _scalar(con: duckdb.DuckDBPyConnection, sql: str) -> object:
    row = con.execute(sql).fetchone()
    return row[0] if row else None


def _metric_value(con: duckdb.DuckDBPyConnection, metric: Metric) -> int | float | dict[str, float]:
    if metric.kind == "bands":
        return {str(label): float(value) for label, value in con.execute(metric.sql).fetchall()}
    value = _scalar(con, metric.sql)
    return float(value or 0) if metric.kind == "float" else int(value or 0)  # type: ignore[arg-type]


def run_checks(con: duckdb.DuckDBPyConnection) -> DataQualityReport:
    """Integrity checks and anomaly metrics; read-only, so it also runs on a runtime connection."""
    checks = []
    for check in INTEGRITY_CHECKS:
        failing = int(_scalar(con, check.sql) or 0)  # type: ignore[arg-type]
        checks.append(IntegrityCheck(name=check.name, description=check.description, passed=failing == 0,
                                     failing_rows=failing))  # fmt: skip
    metrics = [
        AnomalyMetric(name=m.name, description=m.description, value=_metric_value(con, m))
        for m in ANOMALY_METRICS
    ]
    return DataQualityReport(
        as_of=_scalar(con, "SELECT getvariable('as_of')"),  # type: ignore[arg-type]
        integrity_checks=checks,
        anomaly_metrics=metrics,
    )


def fingerprints(con: duckdb.DuckDBPyConnection) -> tuple[dict[str, int], dict[str, str]]:
    """Row counts of every warehouse table and an order-independent md5 per gold object."""
    tables = con.execute(
        "SELECT table_schema || '.' || table_name FROM information_schema.tables "
        "WHERE table_schema IN ('bronze', 'silver', 'gold', 'ref') AND table_type = 'BASE TABLE' ORDER BY 1"
    ).fetchall()
    counts = {name: int(_scalar(con, f"SELECT count(*) FROM {name}")) for (name,) in tables}  # type: ignore[arg-type]
    checksums = {
        name: str(
            _scalar(con, f"SELECT md5(string_agg(CAST(t AS VARCHAR), chr(10) ORDER BY {keys})) FROM {name} t")
        )
        for name, keys in GOLD_KEYS.items()
    }
    return counts, checksums
