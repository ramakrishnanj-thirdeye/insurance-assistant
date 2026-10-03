"""get_qdrant: Qdrant local mode locks its folder to one process (ADR-002)."""

import logging
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from qdrant_client import QdrantClient, models

from insurai import settings as settings_module
from insurai.retrieval import index
from insurai.retrieval.client import STOP_SERVICES, IndexLockedError, get_qdrant

pytestmark = pytest.mark.integration

HOLDER = (
    "import sys; from qdrant_client import QdrantClient; c = QdrantClient(path=sys.argv[1]); "
    "print('ready', flush=True); sys.stdin.read()"
)


@pytest.fixture
def tiny_index(tmp_path: Path) -> Path:
    path = tmp_path / "qdrant"
    client = QdrantClient(path=str(path))
    client.create_collection("c", vectors_config=models.VectorParams(size=2, distance=models.Distance.COSINE))
    client.upsert("c", [models.PointStruct(id=1, vector=[1.0, 0.0], payload={"k": "v"})])
    client.close()
    return path


@pytest.fixture
def held(tiny_index: Path) -> Iterator[Path]:
    """Another process (think `make api`) holds the index open."""
    proc = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(tiny_index)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert proc.stdout is not None and proc.stdout.readline().strip() == "ready"
    yield tiny_index
    proc.communicate(input="", timeout=30)


def test_AC_04_12_unlocked_reader_opens_the_index_itself(tiny_index: Path) -> None:
    client = get_qdrant(path=tiny_index)
    try:
        assert client.count("c").count == 1
    finally:
        client.close()


def test_AC_04_12_reader_falls_back_to_copy_when_locked(held: Path) -> None:
    client = get_qdrant(read_only=True, path=held)
    try:
        assert client.count("c").count == 1
        hits = client.query_points("c", query=[1.0, 0.0], limit=1).points
        assert hits[0].payload == {"k": "v"}
    finally:
        client.close()


def test_AC_04_12_writer_fails_with_stop_services_message(held: Path) -> None:
    with pytest.raises(IndexLockedError, match="stop make api / make mcp / make ui, then rerun make index"):
        get_qdrant(read_only=False, path=held)


def test_AC_04_12_make_index_exits_nonzero_when_locked(
    held: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("INSURAI__PATHS__QDRANT_PATH", str(held))
    settings_module.get_settings.cache_clear()
    monkeypatch.setattr(logging.getLogger("insurai"), "propagate", True)
    with caplog.at_level(logging.ERROR, logger="insurai"):
        assert index.main() != 0
    assert STOP_SERVICES in caplog.text


def test_reader_on_missing_index_says_run_make_index(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="make index"):
        get_qdrant(path=tmp_path / "absent")
    assert not (tmp_path / "absent").exists()
