"""Build data/warehouse.duckdb from the delivered CSVs (spec 01).

Run as ``python -m insurai.ingest.build_warehouse``. Builds into ``<warehouse>.tmp``, runs the data-quality
checks, writes the report, and only then atomically replaces the warehouse. An integrity failure keeps the
previous warehouse and exits non-zero.
"""

import os
import sys
import time
from pathlib import Path

import duckdb

from insurai import settings as settings_module
from insurai.db import set_variables
from insurai.ingest.quality import fingerprints, run_checks
from insurai.ingest.ref_tables import load_ref_tables
from insurai.ingest.schemas import DataQualityReport, RefTablesReport, WarehouseReport
from insurai.observability import get_logger
from insurai.settings import Settings, get_settings

log = get_logger("ingest.build_warehouse")

SQL_DIR = Path(__file__).parent / "sql"


class WarehouseIntegrityError(RuntimeError):
    def __init__(self, report: DataQualityReport) -> None:
        failed = [c.name for c in report.integrity_checks if not c.passed]
        super().__init__(f"integrity checks failed: {', '.join(failed)}")
        self.report = report


def _sibling(path: Path, suffix: str) -> Path:
    return path.with_name(path.name + suffix)


def _unlink(*paths: Path) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


def _run_build(
    con: duckdb.DuckDBPyConnection, settings: Settings
) -> tuple[DataQualityReport, RefTablesReport]:
    set_variables(con, settings.as_of_date, settings.thresholds.high_value_inr, settings.paths.raw_dir)
    ref = load_ref_tables(con, settings_module.CONFIG_FILE.parent)
    for sql_file in sorted(SQL_DIR.glob("*.sql")):
        log.info("running %s", sql_file.name)
        con.execute(sql_file.read_text(encoding="utf-8"))
    report = run_checks(con)
    row_counts, checksums = fingerprints(con)
    return report.model_copy(update={"row_counts": row_counts, "gold_checksums": checksums}), ref


def build(settings: Settings) -> WarehouseReport:
    """Build the warehouse and the data-quality report; raise WarehouseIntegrityError on integrity failure."""
    start = time.perf_counter()
    target, dq_path = settings.paths.warehouse, settings.paths.dq_report
    tmp = _sibling(target, ".tmp")
    target.parent.mkdir(parents=True, exist_ok=True)
    _unlink(tmp, _sibling(tmp, ".wal"))

    con = duckdb.connect(str(tmp))
    try:
        dq, ref = _run_build(con, settings)
        con.execute("CHECKPOINT")
    finally:
        con.close()

    dq_path.parent.mkdir(parents=True, exist_ok=True)
    dq_path.write_text(dq.model_dump_json(indent=2), encoding="utf-8")
    if not dq.integrity_passed:
        _unlink(tmp, _sibling(tmp, ".wal"))
        raise WarehouseIntegrityError(dq)

    try:
        _unlink(_sibling(target, ".wal"))  # a stale WAL would be replayed onto the new file
        os.replace(tmp, target)
    except PermissionError as exc:
        raise PermissionError(
            f"cannot replace {target}: it is open in another process (stop make api / mcp / ui first)"
        ) from exc

    p95 = dq.metric("claim_amount_p95").value
    log.info(
        "claim_amount p95 = %s (thresholds.high_value_inr = %s)", p95, settings.thresholds.high_value_inr
    )
    report = WarehouseReport(
        warehouse_path=target,
        dq_report_path=dq_path,
        build_seconds=round(time.perf_counter() - start, 2),
        ref=ref,
        data_quality=dq,
    )
    log.info("warehouse built at %s in %.1fs", target, report.build_seconds)
    return report


def main(settings: Settings | None = None) -> int:
    try:
        build(settings or get_settings())
    except WarehouseIntegrityError as exc:
        for check in exc.report.integrity_checks:
            if not check.passed:
                log.error(
                    "integrity check %s failed on %d rows: %s",
                    check.name,
                    check.failing_rows,
                    check.description,
                )
        log.error("warehouse not replaced; see the data-quality report")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
