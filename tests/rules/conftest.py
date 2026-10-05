"""Rules tests: a read-only connection to the real warehouse."""

from collections.abc import Iterator

import duckdb
import pytest

from insurai import db
from insurai.settings import get_settings


@pytest.fixture
def warehouse_ready() -> None:
    if not get_settings().paths.warehouse.exists():
        pytest.skip("data/warehouse.duckdb not built: run `make data`")


@pytest.fixture
def warehouse(warehouse_ready: None) -> Iterator[duckdb.DuckDBPyConnection]:
    with db.connect(read_only=True) as con:
        yield con
