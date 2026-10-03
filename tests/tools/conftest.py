"""Fixtures for tool tests: persona contexts and IDs picked from the real warehouse (read-only)."""

from collections.abc import Iterator

import duckdb
import pytest
from tool_ids import KNOWN_OWNER

from insurai import db
from insurai.settings import get_settings


@pytest.fixture(scope="session")
def warehouse() -> Iterator[duckdb.DuckDBPyConnection]:
    if not get_settings().paths.warehouse.exists():
        pytest.skip("data/warehouse.duckdb not built: run `make data`")
    with db.connect(read_only=True) as con:
        yield con


@pytest.fixture(scope="session")
def other_customer(warehouse: duckdb.DuckDBPyConnection) -> str:
    """A real customer who owns neither KNOWN_CLAIM nor KNOWN_POLICY."""
    row = warehouse.execute(
        "SELECT customer_id FROM silver.customers WHERE customer_id <> ? ORDER BY customer_id LIMIT 1",
        [KNOWN_OWNER],
    ).fetchone()
    assert row is not None
    return str(row[0])


@pytest.fixture(scope="session")
def claim_with_interactions(warehouse: duckdb.DuckDBPyConnection) -> tuple[str, str]:
    """(claim_id, owner) of a claim with at least two interactions."""
    row = warehouse.execute(
        """SELECT claim_id, any_value(claim_owner_id) FROM silver.customer_interactions
           GROUP BY claim_id HAVING count(*) >= 2 ORDER BY claim_id LIMIT 1"""
    ).fetchone()
    assert row is not None
    return str(row[0]), str(row[1])
