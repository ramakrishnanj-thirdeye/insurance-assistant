"""Agent graph fixtures: a fresh in-memory graph per test behind the warehouse gate."""

from typing import Any

import pytest

from insurai.settings import get_settings


@pytest.fixture
def warehouse_ready() -> None:
    if not get_settings().paths.warehouse.exists():
        pytest.skip("data/warehouse.duckdb not built: run `make data`")


@pytest.fixture
def graph(warehouse_ready: None) -> Any:
    from insurai.agent.checkpoint import memory_saver
    from insurai.agent.graph import build_graph

    return build_graph(memory_saver())
