"""search_policy: glossary → filter → hybrid search (RRF) → rerank + section boost → gate → context pack.

Stage numbers follow spec 04 Pipeline; stage 2 (LLM rewrite) is deferred for the 3-day delivery.
"""

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from qdrant_client import QdrantClient, models

from insurai.knowledge.parse import ALL, slug
from insurai.knowledge.schemas import PolicyChunk
from insurai.observability import get_logger
from insurai.retrieval import embed
from insurai.retrieval.client import get_qdrant
from insurai.retrieval.glossary import expand
from insurai.retrieval.index import DENSE, SPARSE, point_id
from insurai.retrieval.schemas import RetrievalConfig, RetrievalResult, RetrievedChunk
from insurai.semantic.schemas import VerifiedQuery
from insurai.settings import get_settings
from insurai.tools.schemas import SourceRef, ToolContext

log = get_logger(__name__)

NEIGHBOUR_RANK = 0  # fused_rank of a context-pack neighbour, which was not ranked by search

_readers: dict[Path, QdrantClient] = {}
_readers_lock = threading.Lock()


def search_policy(
    ctx: ToolContext,
    query: str,
    product: str | None = None,
    policy_type: str | None = None,
    section_hints: list[int] | None = None,
    cfg: RetrievalConfig | None = None,
) -> RetrievalResult:
    cfg = cfg or RetrievalConfig()
    if cfg.use_rewrite:
        raise NotImplementedError("LLM rewrite (spec 04 stage 2) is deferred: 3-day scope")
    if not (cfg.use_dense or cfg.use_sparse):
        raise ValueError("RetrievalConfig needs use_dense or use_sparse")
    s = get_settings().retrieval
    timings: dict[str, float] = {}
    start = time.perf_counter()

    with _timed(timings, "glossary"):
        expanded, glossary_hints = expand(query) if cfg.use_glossary else (query, [])
    hints = list(dict.fromkeys([*(section_hints or []), *glossary_hints]))
    flt, filters, unfiltered = build_filter(product, policy_type, cfg.use_filter)

    client = _reader()
    with _timed(timings, "embed"):
        dense = next(iter(embed.dense_model().query_embed(expanded))).tolist() if cfg.use_dense else None
        sparse = _sparse_query(expanded) if cfg.use_sparse else None
    with _timed(timings, "search"):
        candidates = _candidates(client, dense, sparse, flt, cfg.prefetch_k)
    with _timed(timings, "rerank"):
        scores = (
            [float(x) for x in embed.reranker().rerank(expanded, [c.embed_text for c in candidates])]
            if cfg.use_rerank and candidates
            else None
        )
        hits = rerank_and_boost(candidates, scores, hints, s.section_boost, cfg.final_k)
    confident = is_confident(hits, s.rerank_threshold, reranked=cfg.use_rerank)
    with _timed(timings, "pack"):
        chunks = context_pack(hits, lambda ids: _lookup(client, ids), s.neighbour_sections)
    timings["total"] = round((time.perf_counter() - start) * 1000, 1)

    log.info(
        "search_policy trace=%s product=%s hits=%s confident=%s total_ms=%.0f",
        ctx.trace_id,
        product,
        [h.chunk.chunk_id for h in hits],
        confident,
        timings["total"],
    )
    return RetrievalResult(
        query=query,
        rewritten_query=expanded,
        filters=filters,
        section_hints=hints,
        chunks=chunks,
        confident=confident,
        timings_ms=timings,
        sources=to_sources(chunks),
        unfiltered=unfiltered,
    )


def similar_sql_examples(question: str, k: int = 3) -> list[VerifiedQuery]:
    """The k verified queries whose question is closest to `question` (few-shots for spec 02)."""
    vector = next(iter(embed.dense_model().query_embed(question))).tolist()
    resp = _reader().query_points(
        get_settings().retrieval.collection_sql_examples,
        query=vector,
        using=DENSE,
        limit=k,
        with_payload=True,
    )
    return [VerifiedQuery.model_validate(p.payload) for p in resp.points]


def build_filter(
    product: str | None, policy_type: str | None, use_filter: bool
) -> tuple[models.Filter | None, dict, bool]:
    """Stage 3. Returns (Qdrant filter, its description for the trace, unfiltered flag)."""
    if use_filter and product:
        allowed = [product, ALL]
        flt = models.Filter(must=[models.FieldCondition(key="product", match=models.MatchAny(any=allowed))])
        return flt, {"product": allowed}, False
    if use_filter and policy_type:
        flt = models.Filter(
            should=[
                models.FieldCondition(key="policy_type", match=models.MatchValue(value=policy_type)),
                models.FieldCondition(key="is_common", match=models.MatchValue(value=True)),
            ]
        )
        return flt, {"policy_type": policy_type, "or_is_common": True}, False
    return None, {}, True


def rerank_and_boost(
    candidates: list[PolicyChunk], scores: list[float] | None, hints: list[int], boost: float, final_k: int
) -> list[RetrievedChunk]:
    """Stage 5. Without scores (rerank off) the fused order stands and no boost applies."""
    if scores is None:
        return [
            RetrievedChunk(chunk=c, fused_rank=i, rerank_score=None, boosted=False, via="search")
            for i, c in enumerate(candidates[:final_k], start=1)
        ]
    ranked = []
    for i, (c, score) in enumerate(zip(candidates, scores, strict=True), start=1):
        boosted = c.section_no in hints
        ranked.append(
            RetrievedChunk(
                chunk=c,
                fused_rank=i,
                rerank_score=score + boost if boosted else score,
                boosted=boosted,
                via="search",
            )
        )
    ranked.sort(key=lambda r: r.rerank_score or 0.0, reverse=True)
    return ranked[:final_k]


def is_confident(hits: list[RetrievedChunk], threshold: float | None, reranked: bool) -> bool:
    """Stage 6. The gate needs rerank scores; without them only an empty result is not confident."""
    if not hits:
        return False
    if threshold is None or not reranked or hits[0].rerank_score is None:
        return True
    return hits[0].rerank_score >= threshold


def context_pack(
    hits: list[RetrievedChunk],
    lookup: Callable[[list[str]], dict[str, PolicyChunk]],
    neighbour_sections: dict[int, list[int]],
) -> list[RetrievedChunk]:
    """Stage 7. Append same-product neighbour sections of product hits; search hits stay first."""
    seen = {h.chunk.chunk_id for h in hits}
    wanted: list[str] = []
    for h in hits:
        if h.chunk.is_common:
            continue
        for section_no in neighbour_sections.get(h.chunk.section_no, []):
            chunk_id = f"{slug(h.chunk.product)}-s{section_no}"
            if chunk_id not in seen and chunk_id not in wanted:
                wanted.append(chunk_id)
    if not wanted:
        return hits
    found = lookup(wanted)
    neighbours = [
        RetrievedChunk(
            chunk=found[i], fused_rank=NEIGHBOUR_RANK, rerank_score=None, boosted=False, via="neighbour"
        )
        for i in wanted
        if i in found
    ]
    return [*hits, *neighbours]


def to_sources(chunks: list[RetrievedChunk]) -> list[SourceRef]:
    """Stage 8. One SourceRef per chunk, labelled with its citation label."""
    return [
        SourceRef(
            kind="policy",
            label=r.chunk.citation_label,
            product=r.chunk.product,
            section_no=r.chunk.section_no,
            section_name=r.chunk.section_name,
        )
        for r in chunks
    ]


def collection_count(collection: str) -> int:
    """Points in `collection` on the process's cached reader (spec 09 /health)."""
    return _reader().count(collection).count


def close_readers() -> None:
    with _readers_lock:
        for client in _readers.values():
            client.close()
        _readers.clear()


def _reader() -> QdrantClient:
    """One read client per index path for the process (opening a local index loads every collection)."""
    path = get_settings().paths.qdrant_path
    with _readers_lock:
        if path not in _readers:
            _readers[path] = get_qdrant(read_only=True, path=path)
        return _readers[path]


def _sparse_query(text: str) -> models.SparseVector:
    vec = next(iter(embed.sparse_model().query_embed(text)))
    return models.SparseVector(indices=vec.indices.tolist(), values=vec.values.tolist())


def _candidates(
    client: QdrantClient,
    dense: list[float] | None,
    sparse: models.SparseVector | None,
    flt: models.Filter | None,
    k: int,
) -> list[PolicyChunk]:
    """Stage 4. Dense and BM25 prefetch fused by RRF, or the one retriever that is switched on."""
    collection = get_settings().retrieval.collection_policies
    if dense is not None and sparse is not None:
        resp = client.query_points(
            collection,
            prefetch=[
                models.Prefetch(query=dense, using=DENSE, filter=flt, limit=k),
                models.Prefetch(query=sparse, using=SPARSE, filter=flt, limit=k),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=k,
            with_payload=True,
        )
    else:
        query, using = (dense, DENSE) if dense is not None else (sparse, SPARSE)
        resp = client.query_points(
            collection, query=query, using=using, query_filter=flt, limit=k, with_payload=True
        )
    return [PolicyChunk.model_validate(p.payload) for p in resp.points]


def _lookup(client: QdrantClient, chunk_ids: list[str]) -> dict[str, PolicyChunk]:
    points = client.retrieve(
        get_settings().retrieval.collection_policies, ids=[point_id(i) for i in chunk_ids], with_payload=True
    )
    chunks = [PolicyChunk.model_validate(p.payload) for p in points]
    return {c.chunk_id: c for c in chunks}


@contextmanager
def _timed(timings: dict[str, float], stage: str) -> Iterator[None]:
    start = time.perf_counter()
    try:
        yield
    finally:
        timings[stage] = round((time.perf_counter() - start) * 1000, 1)
