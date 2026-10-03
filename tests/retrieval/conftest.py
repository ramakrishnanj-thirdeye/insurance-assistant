"""Shared fixtures for retrieval tests: a private index built from the real chunks, never data/qdrant."""

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from insurai.retrieval.client import get_qdrant
from insurai.retrieval.index import build_policy_index, build_sql_examples_index
from insurai.retrieval.schemas import IndexReport
from insurai.semantic.model import SemanticModel

from insurai import settings as settings_module
from insurai.knowledge.parse import build_chunks, parse_corpus
from insurai.knowledge.schemas import PolicyChunk
from insurai.retrieval import embed, search
from insurai.settings import get_settings
from insurai.tools.schemas import ToolContext


@pytest.fixture(scope="session")
def models_ready() -> None:
    """Skip, never download: `make test` on a fresh clone must not fetch ~1 GB of models."""
    if not embed.models_cached():
        pytest.skip("fastembed models not cached: run make index first")


@pytest.fixture(scope="session")
def policy_chunks() -> list[PolicyChunk]:
    return build_chunks(parse_corpus(get_settings().paths.policy_docs_dir))


@pytest.fixture(scope="session")
def built_index(
    models_ready: None, policy_chunks: list[PolicyChunk], tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, IndexReport, IndexReport]:
    path = tmp_path_factory.mktemp("qdrant")
    client = get_qdrant(read_only=False, path=path)
    try:
        policies = build_policy_index(policy_chunks, client=client)
        examples = build_sql_examples_index(SemanticModel.load(), client=client)
    finally:
        client.close()
    return path, policies, examples


@pytest.fixture
def index_path(
    built_index: tuple[Path, IndexReport, IndexReport], monkeypatch: pytest.MonkeyPatch
) -> Iterator[Path]:
    """Point settings.paths.qdrant_path at the private index for this test."""
    path = built_index[0]
    monkeypatch.setenv("INSURAI__PATHS__QDRANT_PATH", str(path))
    settings_module.get_settings.cache_clear()
    yield path
    settings_module.get_settings.cache_clear()


@pytest.fixture(scope="session", autouse=True)
def _close_cached_readers() -> Iterator[None]:
    yield
    search.close_readers()


@pytest.fixture
def ctx() -> ToolContext:
    return ToolContext(persona="claims_agent", as_of=date(2026, 10, 1), trace_id="test")
