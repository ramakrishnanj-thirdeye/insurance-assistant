"""Acceptance checks against the real warehouse built by `make data` (read-only)."""

import json
import statistics
import time
from collections.abc import Iterator

import duckdb
import pytest
from insurai.ingest.quality import run_checks
from insurai.ingest.schemas import DataQualityReport

from insurai import db
from insurai.settings import get_settings

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def con() -> Iterator[duckdb.DuckDBPyConnection]:
    if not get_settings().paths.warehouse.exists():
        pytest.skip("data/warehouse.duckdb not built: run `make data`")
    with db.connect(read_only=True) as con:
        yield con


@pytest.fixture(scope="module")
def dq_report() -> DataQualityReport:
    path = get_settings().paths.dq_report
    if not path.exists():
        pytest.skip("data quality report not built: run `make data`")
    return DataQualityReport.model_validate(json.loads(path.read_text(encoding="utf-8")))


ROW_COUNTS = {
    "customers": 50_000,
    "policies": 75_000,
    "claims": 120_000,
    "claim_documents": 600_010,
    "hospitals": 1_200,
    "customer_interactions": 180_000,
}


@pytest.mark.parametrize(("table", "rows"), ROW_COUNTS.items())
def test_AC_01_02_row_counts(con: duckdb.DuckDBPyConnection, table: str, rows: int) -> None:
    assert con.execute(f"SELECT count(*) FROM bronze.{table}").fetchone() == (rows,)
    assert con.execute(f"SELECT count(*) FROM silver.{table}").fetchone() == (rows,)


def test_AC_01_02_gold_grain(con: duckdb.DuckDBPyConnection) -> None:
    assert con.execute("SELECT count(*), count(DISTINCT claim_id) FROM gold.claim_facts").fetchone() == (
        120_000,
        120_000,
    )
    assert con.execute("SELECT count(*) FROM gold.v_customer_360").fetchone() == (50_000,)


def test_AC_01_03_real_warehouse_integrity_passes(
    con: duckdb.DuckDBPyConnection, dq_report: DataQualityReport
) -> None:
    assert dq_report.integrity_passed
    rerun = run_checks(con)
    assert rerun.integrity_passed, [c.name for c in rerun.integrity_checks if not c.passed]


ANOMALIES = {
    "claims_in_policy_period": 21_625,
    "claims_before_policy_start": 35_295,
    "claims_after_policy_end": 63_080,
    "policies_in_force": 9_647,
    "policies_lapsed": 63_107,
    "policies_cancelled": 2_246,
    "policies_active_not_in_force": 50_811,
    "interactions_logged_customer_not_owner": 179_999,
    "interactions_before_claim_date": 66_401,
    "policies_extending_chain": 2_110,
    "policies_in_multi_policy_chain": 4_171,
    "policies_back_to_back_renewal": 12,
    "approved_claims_with_missing_upload": 21_775,
}


@pytest.mark.parametrize(("name", "value"), ANOMALIES.items())
def test_AC_01_04_anomaly_metrics_match_spec(
    con: duckdb.DuckDBPyConnection, dq_report: DataQualityReport, name: str, value: int
) -> None:
    assert dq_report.metric(name).value == value
    assert run_checks(con).metric(name).value == value


def test_AC_01_04_interactions_total_and_schedule_waiting_share(dq_report: DataQualityReport) -> None:
    assert dq_report.metric("interactions_total").value == 180_000
    share = dq_report.metric("policies_schedule_waiting_730_plus_share").value
    assert isinstance(share, float) and 0.195 <= share <= 0.205


def test_AC_01_04_fraud_review_rate_per_band(dq_report: DataQualityReport) -> None:
    rates = dq_report.metric("fraud_review_rate_by_score_band").value
    assert isinstance(rates, dict)
    expected = {
        "0.0-0.2": 100 * 14_902 / 83_851,
        "0.2-0.4": 100 * 5_689 / 31_455,
        "0.4-0.6": 100 * 826 / 4_470,
        "0.6-1.0": 100 * 49 / 224,
    }
    assert rates == pytest.approx(expected, abs=1e-6)
    assert round(min(rates.values()), 1) == 17.8 and round(max(rates.values()), 1) == 21.9


DEMO_CHECKLISTS = {
    "CLM300210": (["Claim Form", "Discharge Summary", "ID Proof", "Prescription"],
                  ["Diagnostic Report", "Hospital Bill"]),
    "CLM300500": (["Policy Copy"], []),
    "CLM300101": (["Prescription"], ["Claim Form"]),
}  # fmt: skip


@pytest.mark.parametrize(("claim_id", "expected"), DEMO_CHECKLISTS.items())
def test_AC_01_06_demo_claim_checklists(
    con: duckdb.DuckDBPyConnection, claim_id: str, expected: tuple[list[str], list[str]]
) -> None:
    missing, pending = con.execute(
        "SELECT coalesce(missing_doc_types, []), coalesce(pending_doc_types, []) "
        "FROM gold.claim_facts WHERE claim_id = ?",
        [claim_id],
    ).fetchone()
    assert (missing, pending) == expected
    checklist = con.execute(
        "SELECT document_type FROM gold.claim_doc_checklist "
        "WHERE claim_id = ? AND required AND checklist_status IN ('Missing', 'No record') ORDER BY 1",
        [claim_id],
    ).fetchall()
    assert [d for (d,) in checklist] == expected[0]


@pytest.mark.parametrize(
    ("claim_id", "payable"), [("CLM300210", 58_119), ("CLM300500", 34_184), ("CLM300101", 57_091)]
)
def test_AC_01_07_expected_payable_demo_claims(
    con: duckdb.DuckDBPyConnection, claim_id: str, payable: int
) -> None:
    assert con.execute(
        "SELECT expected_payable FROM gold.claim_facts WHERE claim_id = ?", [claim_id]
    ).fetchone() == (payable,)


def test_AC_01_08_real_report_lists_every_check_and_metric(dq_report: DataQualityReport) -> None:
    assert len(dq_report.integrity_checks) >= 16
    assert all(c.description and isinstance(c.passed, bool) for c in dq_report.integrity_checks)
    assert all(m.description and m.value is not None for m in dq_report.anomaly_metrics)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM gold.claim_facts WHERE claim_id = ?",
        "SELECT * FROM gold.claim_doc_checklist WHERE claim_id = ?",
        "SELECT * FROM gold.v_claim_360 WHERE claim_id = ?",
    ],
)
def test_AC_01_11_single_claim_lookup_under_50ms(con: duckdb.DuckDBPyConnection, sql: str) -> None:
    con.execute(sql, ["CLM300000"]).fetchall()  # warm-up
    timings = []
    for claim_id in ("CLM300210", "CLM300500", "CLM300101", "CLM350000", "CLM419999"):
        start = time.perf_counter()
        rows = con.execute(sql, [claim_id]).fetchall()
        timings.append(time.perf_counter() - start)
        assert rows
    assert statistics.median(timings) < 0.050, timings
