"""DuckDB connections to the warehouse (spec 01). Runtime code always connects read-only."""

from datetime import date
from pathlib import Path

import duckdb

from insurai.settings import get_settings


def set_variables(
    con: duckdb.DuckDBPyConnection, as_of: date, high_value: int, raw_dir: Path | None = None
) -> None:
    """The session variables the warehouse SQL and runtime queries read via getvariable()."""
    con.execute("SET VARIABLE as_of = CAST(? AS DATE)", [as_of])
    con.execute("SET VARIABLE high_value = CAST(? AS BIGINT)", [high_value])
    if raw_dir is not None:
        con.execute("SET VARIABLE raw_dir = ?", [raw_dir.as_posix()])


def connect(read_only: bool = True, path: Path | None = None) -> duckdb.DuckDBPyConnection:
    """Open the warehouse (default ``paths.warehouse``) with ``as_of`` and ``high_value`` set."""
    settings = get_settings()
    target = path or settings.paths.warehouse
    if read_only and not target.exists():
        raise FileNotFoundError(f"warehouse not found at {target}: run `make data`")
    con = duckdb.connect(str(target), read_only=read_only)
    set_variables(con, settings.as_of_date, settings.thresholds.high_value_inr)
    return con
