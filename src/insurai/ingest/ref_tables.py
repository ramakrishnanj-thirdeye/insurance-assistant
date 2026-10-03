"""Reference tables loaded from config YAML: ref.required_documents and ref.diagnosis_coverage (spec 01)."""

from pathlib import Path

import duckdb
import yaml

from insurai.ingest.schemas import RefTablesReport, RequiredDocumentsConfig
from insurai.knowledge.coverage import coverage_grid, load_coverage
from insurai.observability import get_logger

__all__ = ["coverage_grid", "load_ref_tables", "required_document_rows"]

log = get_logger(__name__)

RequiredDocRow = tuple[str, str, str | None, list[str] | None]


def required_document_rows(cfg: RequiredDocumentsConfig) -> list[RequiredDocRow]:
    """One row per `always` document (no condition) and per conditional document.

    `optional` documents are not required, so they get no row.
    """
    rows: list[RequiredDocRow] = []
    for ptype, spec in cfg.policy_types.items():
        rows.extend((ptype, doc, None, None) for doc in spec.always)
        for cond in spec.conditional:
            rows.extend((ptype, doc, cond.when.field_name, cond.when.values) for doc in cond.add)
    return rows


def load_ref_tables(con: duckdb.DuckDBPyConnection, config_dir: Path) -> RefTablesReport:
    required = RequiredDocumentsConfig.model_validate(
        yaml.safe_load((config_dir / "required_documents.yaml").read_text(encoding="utf-8"))
    )
    if required.status != "approved":
        log.warning("required_documents.yaml has status %r (open decision #3)", required.status)
    matrix = load_coverage(config_dir / "coverage_matrix.yaml")

    con.execute("CREATE SCHEMA IF NOT EXISTS ref")
    con.execute(
        "CREATE OR REPLACE TABLE ref.required_documents (policy_type VARCHAR NOT NULL, "
        "document_type VARCHAR NOT NULL, condition_field VARCHAR, condition_values VARCHAR[])"
    )
    doc_rows = required_document_rows(required)
    con.executemany("INSERT INTO ref.required_documents VALUES (?, ?, ?, ?)", doc_rows)

    con.execute(
        "CREATE OR REPLACE TABLE ref.diagnosis_coverage (product_name VARCHAR NOT NULL, "
        "diagnosis VARCHAR NOT NULL, coverage_status VARCHAR NOT NULL, "
        "required_waiting_days INTEGER NOT NULL, "
        "waiting_basis VARCHAR, waiting_reason VARCHAR, section_no INTEGER, coverage_basis VARCHAR NOT NULL, "
        "reason VARCHAR, PRIMARY KEY (product_name, diagnosis))"
    )
    grid = coverage_grid(matrix)
    con.executemany(
        "INSERT INTO ref.diagnosis_coverage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                r.product_name, r.diagnosis, r.coverage_status, r.required_waiting_days, r.waiting_basis,
                r.waiting_reason, r.section_no, r.coverage_basis, r.reason,
            )
            for r in grid
        ],
    )  # fmt: skip
    return RefTablesReport(
        required_documents_rows=len(doc_rows),
        diagnosis_coverage_rows=len(grid),
        required_documents_status=required.status,
        coverage_matrix_status=matrix.status,
    )
