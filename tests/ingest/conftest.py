"""Fixtures over the tiny raw dataset in tiny_raw.py."""

import copy
from collections.abc import Callable
from pathlib import Path

import pytest
from tiny_raw import TINY, Tables, settings_for, write_raw

from insurai.settings import Settings


@pytest.fixture
def tiny_tables() -> Tables:
    return copy.deepcopy(TINY)


@pytest.fixture
def tiny_settings(tmp_path: Path) -> Callable[[Tables], Settings]:
    """Write the given tables as CSVs under tmp_path and return settings pointing at them."""

    def make(tables: Tables) -> Settings:
        return settings_for(tmp_path, write_raw(tables, tmp_path / "raw"))

    return make
