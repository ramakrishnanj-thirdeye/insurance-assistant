"""Retrieval test fixtures. The private-index fixtures live in tests/conftest.py (shared with tools tests)."""

from datetime import date

import pytest

from insurai.tools.schemas import ToolContext


@pytest.fixture
def ctx() -> ToolContext:
    return ToolContext(persona="claims_agent", as_of=date(2026, 10, 1), trace_id="test")
