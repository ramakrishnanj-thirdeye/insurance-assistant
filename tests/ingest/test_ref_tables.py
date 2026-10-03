from collections.abc import Iterator

import duckdb
import pytest

from insurai.ingest import ref_tables
from insurai.knowledge import coverage
from insurai.settings import ROOT

pytestmark = pytest.mark.unit

CONFIG_DIR = ROOT / "config"


@pytest.fixture
def con() -> Iterator[duckdb.DuckDBPyConnection]:
    con = duckdb.connect()
    yield con
    con.close()


def test_AC_01_05_ref_table_loaded(con: duckdb.DuckDBPyConnection) -> None:
    report = ref_tables.load_ref_tables(con, CONFIG_DIR)
    assert report.diagnosis_coverage_rows == 85
    assert con.execute(
        "SELECT count(*), count(*) FILTER (WHERE required_waiting_days > 0) FROM ref.diagnosis_coverage"
    ).fetchone() == (85, 32)
    row = con.execute(
        "SELECT coverage_status, required_waiting_days, waiting_basis, section_no "
        "FROM ref.diagnosis_coverage "
        "WHERE product_name = 'Critical Care Elite' AND diagnosis = 'Cardiac Procedure'"
    ).fetchone()
    assert row == ("covered", 90, "assumption", 4)


def test_AC_01_05_coverage_grid_is_the_spec_03_function() -> None:
    assert ref_tables.coverage_grid is coverage.coverage_grid


def test_AC_01_06_required_documents_one_row_per_always_and_conditional_doc(
    con: duckdb.DuckDBPyConnection,
) -> None:
    report = ref_tables.load_ref_tables(con, CONFIG_DIR)
    rows = con.execute(
        "SELECT policy_type, document_type, condition_field, condition_values FROM ref.required_documents"
    ).fetchall()
    assert report.required_documents_rows == len(rows) == 6 + 1 + 4 + 4 + 2
    assert ("Health", "Cancelled Cheque", "network_status", ["Non-Network"]) in rows
    assert ("Travel", "Hospital Bill", "diagnosis_or_loss_type", ["Medical Emergency"]) in rows
    assert ("Motor", "Policy Copy", None, None) in rows
    assert not any(doc == "Policy Copy" for ptype, doc, _, _ in rows if ptype == "Health")  # optional


def test_AC_01_06_unknown_document_type_is_rejected() -> None:
    from insurai.ingest.schemas import RequiredDocumentsConfig

    with pytest.raises(ValueError, match="Selfie"):
        RequiredDocumentsConfig.model_validate(
            {
                "version": 1,
                "status": "proposed",
                "document_types": ["Claim Form"],
                "policy_types": {
                    "Health": {"always": ["Claim Form", "Selfie"], "conditional": [], "optional": [],
                               "untracked": [], "source": "s"},
                },
            }
        )  # fmt: skip
