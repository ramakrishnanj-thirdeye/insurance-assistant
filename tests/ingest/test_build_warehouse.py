import time
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest
from tiny_raw import Tables, settings_for

from insurai import db
from insurai.ingest.build_warehouse import build, main
from insurai.settings import Settings, get_settings

TinySettings = Callable[[Tables], Settings]


def _wal(path: Path) -> Path:
    return path.with_name(path.name + ".wal")


@pytest.mark.unit
def test_AC_01_03_build_writes_warehouse_and_report_atomically(
    tiny_settings: TinySettings, tiny_tables: Tables
) -> None:
    settings = tiny_settings(tiny_tables)
    report = build(settings)
    target = settings.paths.warehouse
    assert target.exists() and settings.paths.dq_report.exists()
    assert not target.with_name(target.name + ".tmp").exists()
    assert report.warehouse_path == target
    assert report.ref.required_documents_rows > 0 and report.ref.diagnosis_coverage_rows == 85


@pytest.mark.unit
def test_AC_01_03_build_exits_nonzero_on_integrity_failure(
    tiny_settings: TinySettings, tiny_tables: Tables
) -> None:
    settings = tiny_settings(tiny_tables)
    assert main(settings) == 0
    good = settings.paths.warehouse.read_bytes()

    tiny_tables["claims"][0]["policy_id"] = "GHOST"
    settings = tiny_settings(tiny_tables)
    assert main(settings) == 1
    assert settings.paths.warehouse.read_bytes() == good  # previous warehouse kept
    assert '"passed": false' in settings.paths.dq_report.read_text(encoding="utf-8")
    assert not settings.paths.warehouse.with_name("warehouse.duckdb.tmp").exists()


@pytest.mark.unit
def test_AC_01_03_build_ignores_leftover_wal(tiny_settings: TinySettings, tiny_tables: Tables) -> None:
    settings = tiny_settings(tiny_tables)
    build(settings)
    _wal(settings.paths.warehouse).write_bytes(b"not a duckdb wal")
    build(settings)
    assert not _wal(settings.paths.warehouse).exists()
    with db.connect(read_only=True, path=settings.paths.warehouse) as con:
        assert con.execute("SELECT count(*) FROM gold.claim_facts").fetchone() == (3,)


@pytest.mark.unit
def test_AC_01_07_expected_payable_deductible_before_co_pay(
    tiny_settings: TinySettings, tiny_tables: Tables
) -> None:
    settings = tiny_settings(tiny_tables)
    build(settings)
    with db.connect(read_only=True, path=settings.paths.warehouse) as con:
        rows = dict(con.execute("SELECT claim_id, expected_payable FROM silver.claims").fetchall())
    # CLM1: min(600,000, SI 500,000) − 5,000 = 495,000 × 0.9; CLM2: 8,000 below the 10,000 deductible.
    assert rows == {"CLM1": 445_500, "CLM2": 0, "CLM3": 20_000}


@pytest.mark.unit
def test_AC_01_06_checklist_statuses_and_conditional_documents(
    tiny_settings: TinySettings, tiny_tables: Tables
) -> None:
    settings = tiny_settings(tiny_tables)
    build(settings)
    with db.connect(read_only=True, path=settings.paths.warehouse) as con:
        rows = con.execute(
            "SELECT claim_id, document_type, required, checklist_status FROM gold.claim_doc_checklist"
        ).fetchall()
    checklist = {(c, d): (r, s) for c, d, r, s in rows}
    assert checklist[("CLM1", "Claim Form")] == (True, "Verified")
    assert checklist[("CLM1", "ID Proof")] == (True, "Missing")
    assert checklist[("CLM1", "Hospital Bill")] == (True, "Pending verification")
    assert checklist[("CLM1", "Discharge Summary")] == (True, "Rejected")
    assert checklist[("CLM1", "Prescription")] == (True, "No record")
    assert checklist[("CLM1", "Cancelled Cheque")] == (True, "No record")  # Non-Network hospital
    assert checklist[("CLM1", "Policy Copy")] == (False, "Verified")  # optional for Health
    clm3 = {d for (c, d), (required, _) in checklist.items() if c == "CLM3" and required}
    assert clm3 == {
        "Claim Form",
        "ID Proof",
        "Policy Copy",
        "Cancelled Cheque",
        "Hospital Bill",
        "Discharge Summary",
    }


@pytest.mark.unit
def test_AC_01_04_derived_policy_and_interaction_columns(
    tiny_settings: TinySettings, tiny_tables: Tables
) -> None:
    settings = tiny_settings(tiny_tables)
    build(settings)
    with db.connect(read_only=True, path=settings.paths.warehouse) as con:
        policies = {
            r[0]: r[1:]
            for r in con.execute(
                "SELECT policy_id, effective_status, status_conflict, continuous_cover_start, days_to_expiry "
                "FROM silver.policies"
            ).fetchall()
        }
        interactions = con.execute(
            "SELECT interaction_id, claim_owner_id, logged_customer_id, before_claim_date "
            "FROM silver.customer_interactions ORDER BY interaction_id"
        ).fetchall()
    assert policies["POL1"] == ("In Force", False, date(2026, 1, 1), 92)
    assert policies["POL2"] == ("Lapsed", True, date(2024, 1, 1), -638)
    assert policies["POL3"][:3] == ("Lapsed", False, date(2024, 1, 1))
    assert policies["POL4"][:2] == ("Cancelled", False)
    assert interactions == [("INT1", "CUST1", "CUST2", True), ("INT2", "CUST1", "CUST1", False)]


@pytest.mark.slow
def test_AC_01_01_full_build_under_60s(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, get_settings().paths.raw_dir)
    start = time.perf_counter()
    report = build(settings)
    elapsed = time.perf_counter() - start
    assert report.data_quality.integrity_passed
    assert elapsed < 60, f"full build took {elapsed:.1f}s"


@pytest.mark.slow
def test_AC_01_09_two_builds_identical_counts_and_checksums(tmp_path: Path) -> None:
    raw_dir = get_settings().paths.raw_dir
    first = build(settings_for(tmp_path / "a", raw_dir)).data_quality
    second = build(settings_for(tmp_path / "b", raw_dir)).data_quality
    assert first.row_counts == second.row_counts
    assert first.gold_checksums == second.gold_checksums
    assert len(first.gold_checksums) == 4
