import os
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from insurai import settings as settings_module

_LEAKY_ENV = ("ANTHROPIC_API_KEY", "OLLAMA_BASE_URL")


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Settings come from config/settings.yaml only: no developer .env, no INSURAI__ overrides."""
    for name in list(os.environ):
        if name.upper().startswith("INSURAI__") or name.upper() in _LEAKY_ENV:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(settings_module, "ENV_FILE", None)
    settings_module.get_settings.cache_clear()
    yield
    settings_module.get_settings.cache_clear()


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail the test on any attempt to open a socket connection."""

    def _blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access attempted in a unit test")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


# Private Qdrant index built from the real chunks, never data/qdrant (retrieval and tools tests).
# Imports are lazy so unit-only runs do not load the embedding stack.


@pytest.fixture(scope="session")
def models_ready() -> None:
    """Skip, never download: `make test` on a fresh clone must not fetch ~1 GB of models."""
    from insurai.retrieval import embed

    if not embed.models_cached():
        pytest.skip("fastembed models not cached: run make index first")


@pytest.fixture(scope="session")
def policy_chunks() -> list[Any]:
    from insurai.knowledge.parse import build_chunks, parse_corpus
    from insurai.settings import get_settings

    return build_chunks(parse_corpus(get_settings().paths.policy_docs_dir))


@pytest.fixture(scope="session")
def built_index(
    models_ready: None, policy_chunks: list[Any], tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, Any, Any]:
    from insurai.retrieval.client import get_qdrant
    from insurai.retrieval.index import build_policy_index, build_sql_examples_index
    from insurai.semantic.model import SemanticModel

    path = tmp_path_factory.mktemp("qdrant")
    client = get_qdrant(read_only=False, path=path)
    try:
        policies = build_policy_index(policy_chunks, client=client)
        examples = build_sql_examples_index(SemanticModel.load(), client=client)
    finally:
        client.close()
    return path, policies, examples


@pytest.fixture
def index_path(built_index: tuple[Path, Any, Any], monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point settings.paths.qdrant_path at the private index for this test."""
    path = built_index[0]
    monkeypatch.setenv("INSURAI__PATHS__QDRANT_PATH", str(path))
    settings_module.get_settings.cache_clear()
    yield path
    settings_module.get_settings.cache_clear()


@pytest.fixture(scope="session", autouse=True)
def _close_cached_readers() -> Iterator[None]:
    yield
    import sys

    search = sys.modules.get("insurai.retrieval.search")
    if search is not None:
        search.close_readers()
