from datetime import date
from pathlib import Path

import duckdb
import pytest

from insurai import db

pytestmark = pytest.mark.unit


@pytest.fixture
def warehouse(tmp_path: Path) -> Path:
    path = tmp_path / "w.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute("CREATE TABLE t AS SELECT 1 AS x")
    return path


def test_AC_01_10_read_only_write_raises(warehouse: Path) -> None:
    with db.connect(path=warehouse) as con:
        assert con.execute("SELECT x FROM t").fetchone() == (1,)
        with pytest.raises(duckdb.Error, match="read-only"):
            con.execute("INSERT INTO t VALUES (2)")
        with pytest.raises(duckdb.Error, match="read-only"):
            con.execute("CREATE TABLE u (y INTEGER)")


def test_AC_01_10_connect_sets_variables(warehouse: Path) -> None:
    with db.connect(path=warehouse) as con:
        as_of, high_value = con.execute("SELECT getvariable('as_of'), getvariable('high_value')").fetchone()
    assert as_of == date(2026, 10, 1)
    assert high_value == 236053


def test_AC_01_10_missing_warehouse_names_make_data(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="make data"):
        db.connect(path=tmp_path / "absent.duckdb")
