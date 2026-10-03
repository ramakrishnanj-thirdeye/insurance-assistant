import time
from pathlib import Path

import pytest
from insurai.retrieval.client import get_qdrant
from insurai.retrieval.index import build_policy_index, build_sql_examples_index, point_id
from insurai.retrieval.schemas import IndexReport
from insurai.semantic.model import SemanticModel

from insurai.knowledge.schemas import PolicyChunk
from insurai.settings import get_settings

pytestmark = pytest.mark.integration

BuiltIndex = tuple[Path, IndexReport, IndexReport]


def test_AC_04_02_index_counts_62_and_14(built_index: BuiltIndex) -> None:
    path, policies, examples = built_index
    assert (policies.points, examples.points) == (62, 14)
    client = get_qdrant(path=path)
    try:
        s = get_settings().retrieval
        assert client.count(s.collection_policies, exact=True).count == 62
        assert client.count(s.collection_sql_examples, exact=True).count == 14
    finally:
        client.close()


def test_AC_04_02_rebuild_is_idempotent_and_under_two_minutes(
    models_ready: None, policy_chunks: list[PolicyChunk], tmp_path: Path
) -> None:
    client = get_qdrant(read_only=False, path=tmp_path / "q")
    try:
        start = time.perf_counter()
        first = build_policy_index(policy_chunks, client=client)
        build_sql_examples_index(SemanticModel.load(), client=client)
        assert time.perf_counter() - start < 120
        ids_first = _ids(client)
        second = build_policy_index(policy_chunks, client=client)
        assert first.points == second.points == 62
        assert _ids(client) == ids_first
    finally:
        client.close()


def test_AC_04_02_point_id_is_uuid5_of_chunk_id() -> None:
    assert point_id("health-secure-plus-s5") == point_id("health-secure-plus-s5")
    assert point_id("health-secure-plus-s5") != point_id("health-secure-plus-s4")
    assert len(point_id("x")) == 36


def test_AC_04_03_every_point_has_dense_sparse_and_full_payload(
    built_index: BuiltIndex, policy_chunks: list[PolicyChunk]
) -> None:
    client = get_qdrant(path=built_index[0])
    try:
        points, _ = client.scroll(
            get_settings().retrieval.collection_policies, limit=100, with_payload=True, with_vectors=True
        )
    finally:
        client.close()
    assert len(points) == 62
    by_id = {c.chunk_id: c for c in policy_chunks}
    for p in points:
        assert isinstance(p.vector, dict)
        dense, sparse = p.vector["dense"], p.vector["bm25"]
        assert isinstance(dense, list) and len(dense) == 384
        assert len(sparse.indices) > 0 and len(sparse.indices) == len(sparse.values)
        assert p.payload is not None
        chunk = PolicyChunk.model_validate(p.payload)
        assert chunk == by_id[chunk.chunk_id]
        assert p.id == point_id(chunk.chunk_id)


def test_sql_examples_payload_has_name_question_sql(built_index: BuiltIndex) -> None:
    client = get_qdrant(path=built_index[0])
    try:
        points, _ = client.scroll(
            get_settings().retrieval.collection_sql_examples, limit=100, with_payload=True
        )
    finally:
        client.close()
    assert {frozenset((p.payload or {}).keys()) for p in points} == {frozenset({"name", "question", "sql"})}


def _ids(client) -> set[str]:  # type: ignore[no-untyped-def]
    points, _ = client.scroll(get_settings().retrieval.collection_policies, limit=100)
    return {str(p.id) for p in points}
