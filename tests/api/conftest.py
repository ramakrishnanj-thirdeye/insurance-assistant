"""API fixtures: the app on a private checkpoints file, with scripted LLMs."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fakes import citing_synth, install, planner_script
from sse_client import ANALYZE, WHY_PENDING

from insurai.settings import get_settings


@pytest.fixture
def checkpoints(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "checkpoints.sqlite"
    monkeypatch.setenv("INSURAI__PATHS__CHECKPOINTS", str(path))
    get_settings.cache_clear()
    return path


@pytest.fixture
def warehouse_ready() -> None:
    if not get_settings().paths.warehouse.exists():
        pytest.skip("data/warehouse.duckdb not built: run `make data`")


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch) -> Any:
    return install(
        monkeypatch,
        {
            "Plan": planner_script({"analyze": ANALYZE, "why is": WHY_PENDING}),
            "AnswerDraft": citing_synth,
        },
    )


@pytest.fixture
def client(checkpoints: Path, warehouse_ready: None, scripted: Any) -> Iterator[Any]:
    from fastapi.testclient import TestClient

    from insurai.api.main import create_app

    with TestClient(create_app()) as c:
        yield c
