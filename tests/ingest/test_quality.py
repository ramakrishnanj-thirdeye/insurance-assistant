import json
from collections.abc import Callable

import pytest
from tiny_raw import Tables

from insurai.ingest.build_warehouse import WarehouseIntegrityError, build
from insurai.ingest.quality import ANOMALY_METRICS, INTEGRITY_CHECKS
from insurai.ingest.schemas import DataQualityReport
from insurai.settings import Settings

pytestmark = pytest.mark.unit

TinySettings = Callable[[Tables], Settings]


def _failed_checks(tiny_settings: TinySettings, tables: Tables) -> set[str]:
    with pytest.raises(WarehouseIntegrityError) as excinfo:
        build(tiny_settings(tables))
    return {c.name for c in excinfo.value.report.integrity_checks if not c.passed}


def _copy_row(tables: Tables, table: str, index: int, **changes: object) -> None:
    tables[table].append({**tables[table][index], **changes})


@pytest.mark.parametrize(
    ("table", "check"),
    [
        ("customers", "pk_customers"),
        ("policies", "pk_policies"),
        ("claims", "pk_claims"),
        ("hospitals", "pk_hospitals"),
        ("customer_interactions", "pk_customer_interactions"),
        ("claim_documents", "pk_claim_documents"),
    ],
)
def test_AC_01_03_duplicate_pk_fails_check(
    tiny_settings: TinySettings, tiny_tables: Tables, table: str, check: str
) -> None:
    _copy_row(tiny_tables, table, 0)
    assert check in _failed_checks(tiny_settings, tiny_tables)


@pytest.mark.parametrize(
    ("table", "column", "check"),
    [
        ("claims", "policy_id", "fk_claims_policies"),
        ("claims", "customer_id", "fk_claims_customers"),
        ("claims", "hospital_id", "fk_claims_hospitals"),
        ("claim_documents", "claim_id", "fk_claim_documents_claims"),
        ("customer_interactions", "claim_id", "fk_customer_interactions_claims"),
        ("customer_interactions", "customer_id", "fk_customer_interactions_customers"),
        ("policies", "customer_id", "fk_policies_customers"),
    ],
)
def test_AC_01_03_orphan_fk_fails_check(
    tiny_settings: TinySettings, tiny_tables: Tables, table: str, column: str, check: str
) -> None:
    tiny_tables[table][0][column] = "GHOST"
    assert check in _failed_checks(tiny_settings, tiny_tables)


def test_AC_01_03_claim_customer_differs_from_policy_holder_fails(
    tiny_settings: TinySettings, tiny_tables: Tables
) -> None:
    tiny_tables["claims"][0]["customer_id"] = "CUST2"  # CLM1 is on POL1, held by CUST1
    assert _failed_checks(tiny_settings, tiny_tables) == {"claim_customer_matches_policy_holder"}


def test_AC_01_03_claim_policy_type_differs_fails(tiny_settings: TinySettings, tiny_tables: Tables) -> None:
    tiny_tables["claims"][0]["policy_type"] = "Motor"  # POL1 is Health
    assert "claim_policy_type_matches_policy" in _failed_checks(tiny_settings, tiny_tables)


def test_AC_01_03_claim_without_coverage_cell_fails(tiny_settings: TinySettings, tiny_tables: Tables) -> None:
    tiny_tables["claims"][0]["diagnosis_or_loss_type"] = "Theft"  # not a Health diagnosis
    assert _failed_checks(tiny_settings, tiny_tables) == {"claim_has_coverage_cell"}


def test_AC_01_03_clean_data_passes_every_check(tiny_settings: TinySettings, tiny_tables: Tables) -> None:
    report = build(tiny_settings(tiny_tables)).data_quality
    assert report.integrity_passed
    assert all(c.passed and c.failing_rows == 0 for c in report.integrity_checks)


def test_AC_01_03_anomalies_never_fail_the_build(tiny_settings: TinySettings, tiny_tables: Tables) -> None:
    # Every claim outside its policy period and every interaction logged by someone else: still builds.
    for claim in tiny_tables["claims"]:
        claim["claim_date"] = "2020-01-01"
    for interaction in tiny_tables["customer_interactions"]:
        interaction["customer_id"] = "CUST3"
    report = build(tiny_settings(tiny_tables)).data_quality
    assert report.integrity_passed
    assert report.metric("claims_before_policy_start").value == 3
    assert report.metric("interactions_logged_customer_not_owner").value == 2


def test_AC_01_08_report_lists_every_check_and_metric_with_description(
    tiny_settings: TinySettings, tiny_tables: Tables
) -> None:
    settings = tiny_settings(tiny_tables)
    build(settings)
    report = DataQualityReport.model_validate(
        json.loads(settings.paths.dq_report.read_text(encoding="utf-8"))
    )
    assert [c.name for c in report.integrity_checks] == [c.name for c in INTEGRITY_CHECKS]
    assert [m.name for m in report.anomaly_metrics] == [m.name for m in ANOMALY_METRICS]
    assert all(c.description.strip() for c in report.integrity_checks)
    assert all(m.description.strip() and m.value is not None for m in report.anomaly_metrics)
    assert report.as_of.isoformat() == "2026-10-01"
    assert report.row_counts["bronze.claims"] == 3
    assert set(report.gold_checksums) == {
        "gold.claim_doc_checklist", "gold.claim_facts", "gold.v_claim_360", "gold.v_customer_360",
    }  # fmt: skip


def test_AC_01_04_tiny_anomaly_metrics(tiny_settings: TinySettings, tiny_tables: Tables) -> None:
    report = build(tiny_settings(tiny_tables)).data_quality
    expected = {
        "claims_in_policy_period": 3,
        "policies_in_force": 1,
        "policies_lapsed": 2,
        "policies_cancelled": 1,
        "policies_active_not_in_force": 1,
        "interactions_logged_customer_not_owner": 1,
        "interactions_before_claim_date": 1,
        "policies_extending_chain": 1,
        "policies_in_multi_policy_chain": 2,
        "policies_back_to_back_renewal": 1,
        "approved_claims_with_missing_upload": 1,
    }
    assert {name: report.metric(name).value for name in expected} == expected
