"""Build the Qdrant collections from scratch (`make index`, spec 04 Index layout)."""

import time
import uuid
import warnings
from collections.abc import Iterator
from contextlib import contextmanager

from qdrant_client import QdrantClient, models

from insurai.knowledge.parse import build_chunks, parse_corpus
from insurai.knowledge.schemas import PolicyChunk
from insurai.observability import get_logger
from insurai.retrieval import embed
from insurai.retrieval.client import IndexLockedError, get_qdrant
from insurai.retrieval.schemas import IndexReport
from insurai.semantic.model import SemanticModel
from insurai.settings import get_settings

log = get_logger(__name__)

DENSE = "dense"
SPARSE = "bm25"
POLICY_PAYLOAD_INDEXES: dict[str, models.PayloadSchemaType] = {
    "product": models.PayloadSchemaType.KEYWORD,
    "policy_type": models.PayloadSchemaType.KEYWORD,
    "section_no": models.PayloadSchemaType.INTEGER,
    "is_common": models.PayloadSchemaType.BOOL,
}


def point_id(key: str) -> str:
    """Stable across rebuilds: UUID5 of the chunk_id (or verified query name)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


def build_policy_index(chunks: list[PolicyChunk], client: QdrantClient | None = None) -> IndexReport:
    """Recreate collection policy_chunks: dense + IDF-weighted BM25 vectors, full chunk payload."""
    s = get_settings().retrieval
    start = time.perf_counter()
    texts = [c.embed_text for c in chunks]
    dense = [v.tolist() for v in embed.dense_model().embed(texts)]
    sparse = list(embed.sparse_model().embed(texts))

    with _writer(client) as qc:
        _recreate(qc, s.collection_policies, len(dense[0]), with_sparse=True)
        with warnings.catch_warnings():  # local mode ignores payload indexes; kept for the server path
            warnings.simplefilter("ignore")
            for field, schema in POLICY_PAYLOAD_INDEXES.items():
                qc.create_payload_index(s.collection_policies, field, field_schema=schema)
        qc.upsert(
            s.collection_policies,
            [
                models.PointStruct(
                    id=point_id(c.chunk_id),
                    vector={
                        DENSE: d,
                        SPARSE: models.SparseVector(indices=sp.indices.tolist(), values=sp.values.tolist()),
                    },
                    payload=c.model_dump(),
                )
                for c, d, sp in zip(chunks, dense, sparse, strict=True)
            ],
        )
        points = qc.count(s.collection_policies, exact=True).count
    return IndexReport(
        collection=s.collection_policies,
        points=points,
        seconds=round(time.perf_counter() - start, 2),
        models=[s.dense_model, s.sparse_model],
    )


def build_sql_examples_index(model: SemanticModel, client: QdrantClient | None = None) -> IndexReport:
    """Recreate collection sql_examples: the verified queries, dense vector of the question only."""
    s = get_settings().retrieval
    start = time.perf_counter()
    queries = model.verified_queries
    dense = [v.tolist() for v in embed.dense_model().embed([q.question for q in queries])]
    with _writer(client) as qc:
        _recreate(qc, s.collection_sql_examples, len(dense[0]), with_sparse=False)
        qc.upsert(
            s.collection_sql_examples,
            [
                models.PointStruct(id=point_id(q.name), vector={DENSE: d}, payload=q.model_dump())
                for q, d in zip(queries, dense, strict=True)
            ],
        )
        points = qc.count(s.collection_sql_examples, exact=True).count
    return IndexReport(
        collection=s.collection_sql_examples,
        points=points,
        seconds=round(time.perf_counter() - start, 2),
        models=[s.dense_model],
    )


def main() -> int:
    try:
        client = get_qdrant(read_only=False)  # before any download: fail fast if the services hold the index
    except IndexLockedError as exc:
        log.error("%s", exc)
        return 1
    try:
        embed.allow_downloads()
        embed.reranker()  # not needed to build, but `make index` is the one step that downloads models
        start = time.perf_counter()
        chunks = build_chunks(parse_corpus(get_settings().paths.policy_docs_dir))
        reports = [
            build_policy_index(chunks, client=client),
            build_sql_examples_index(SemanticModel.load(), client=client),
        ]
    finally:
        client.close()
    for r in reports:
        log.info(
            "collection %s: %d points in %.1fs (%s)", r.collection, r.points, r.seconds, ", ".join(r.models)
        )
    log.info("index built in %.1fs at %s", time.perf_counter() - start, get_settings().paths.qdrant_path)
    return 0


@contextmanager
def _writer(client: QdrantClient | None) -> Iterator[QdrantClient]:
    """The caller's client as is, or a writer client opened and closed here."""
    if client is not None:
        yield client
        return
    own = get_qdrant(read_only=False)
    try:
        yield own
    finally:
        own.close()


def _recreate(qc: QdrantClient, name: str, size: int, with_sparse: bool) -> None:
    if qc.collection_exists(name):
        qc.delete_collection(name)
    qc.create_collection(
        name,
        vectors_config={DENSE: models.VectorParams(size=size, distance=models.Distance.COSINE)},
        sparse_vectors_config={SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)}
        if with_sparse
        else None,
    )


if __name__ == "__main__":
    raise SystemExit(main())
