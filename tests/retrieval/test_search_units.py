"""Pure pipeline stages of search_policy: no models, no index."""

import pytest
from insurai.retrieval.schemas import RetrievalConfig, RetrievedChunk
from insurai.retrieval.search import build_filter, context_pack, is_confident, rerank_and_boost, to_sources
from qdrant_client import models

from insurai.knowledge.parse import citation_label, slug
from insurai.knowledge.schemas import PolicyChunk

pytestmark = pytest.mark.unit


def chunk(
    product: str, section_no: int, name: str = "Name", policy_type: str | None = "Health"
) -> PolicyChunk:
    common = product == "ALL"
    chunk_id = f"all-s{section_no}" if common else f"{slug(product)}-s{section_no}"
    return PolicyChunk(
        chunk_id=chunk_id,
        product=product,
        policy_type=None if common else policy_type,
        section_no=section_no,
        section_name=name,
        is_common=common,
        text="text",
        header="header",
        embed_text="header: text",
        citation_label=citation_label(product, section_no, name),
        content_hash="h",
        source_path="p",
    )


def hit(c: PolicyChunk, rank: int, score: float | None = None, boosted: bool = False) -> RetrievedChunk:
    return RetrievedChunk(chunk=c, fused_rank=rank, rerank_score=score, boosted=boosted, via="search")


def test_AC_04_06_build_filter_product_matches_product_or_all() -> None:
    flt, desc, unfiltered = build_filter("Health Secure Plus", None, use_filter=True)
    assert desc == {"product": ["Health Secure Plus", "ALL"]}
    assert not unfiltered
    assert flt is not None and flt.must is not None
    cond = flt.must[0]
    assert isinstance(cond, models.FieldCondition) and cond.key == "product"
    assert isinstance(cond.match, models.MatchAny) and cond.match.any == ["Health Secure Plus", "ALL"]


def test_AC_04_06_build_filter_policy_type_or_common() -> None:
    flt, desc, unfiltered = build_filter(None, "Motor", use_filter=True)
    assert desc == {"policy_type": "Motor", "or_is_common": True}
    assert not unfiltered
    assert flt is not None and flt.should is not None and len(flt.should) == 2


def test_AC_04_06_build_filter_product_wins_over_policy_type() -> None:
    _, desc, _ = build_filter("Car Shield Plus", "Motor", use_filter=True)
    assert desc == {"product": ["Car Shield Plus", "ALL"]}


def test_AC_04_06_build_filter_none_flags_unfiltered() -> None:
    assert build_filter(None, None, use_filter=True) == (None, {}, True)


def test_AC_04_06_build_filter_switched_off_is_unfiltered() -> None:
    assert build_filter("Health Secure Plus", None, use_filter=False) == (None, {}, True)


def test_rerank_adds_section_boost_and_flags_it() -> None:
    a, b = chunk("Health Secure Plus", 9), chunk("Health Secure Plus", 5)
    out = rerank_and_boost([a, b], [1.0, 0.95], hints=[5], boost=0.1, final_k=5)
    assert [r.chunk.section_no for r in out] == [5, 9]
    assert out[0].boosted and out[0].rerank_score == pytest.approx(1.05)
    assert not out[1].boosted and out[1].rerank_score == pytest.approx(1.0)
    assert [r.fused_rank for r in out] == [2, 1]


def test_rerank_keeps_final_k() -> None:
    chunks = [chunk("Health Secure Plus", n) for n in (2, 4, 5, 9, 10)]
    out = rerank_and_boost(chunks, [0.1, 0.5, 0.3, 0.9, 0.2], hints=[], boost=0.1, final_k=2)
    assert [r.chunk.section_no for r in out] == [9, 4]


def test_no_rerank_keeps_fused_order_without_scores() -> None:
    chunks = [chunk("Health Secure Plus", n) for n in (2, 4, 5)]
    out = rerank_and_boost(chunks, None, hints=[5], boost=0.1, final_k=2)
    assert [r.chunk.section_no for r in out] == [2, 4]
    assert all(r.rerank_score is None and not r.boosted for r in out)


def test_confidence_gate() -> None:
    hits = [hit(chunk("Health Secure Plus", 5), 1, score=0.4)]
    assert is_confident(hits, threshold=None, reranked=True)
    assert is_confident(hits, threshold=0.3, reranked=True)
    assert not is_confident(hits, threshold=0.5, reranked=True)
    assert is_confident(hits, threshold=0.5, reranked=False)
    assert not is_confident([], threshold=None, reranked=True)


def test_context_pack_adds_same_product_neighbours_after_hits() -> None:
    s5, s9 = chunk("Health Secure Plus", 5), chunk("Health Secure Plus", 9)
    s4 = chunk("Health Secure Plus", 4)
    asked: list[list[str]] = []

    def lookup(ids: list[str]) -> dict[str, PolicyChunk]:
        asked.append(ids)
        return {c.chunk_id: c for c in (s4,) if c.chunk_id in ids}

    out = context_pack([hit(s5, 1), hit(s9, 2)], lookup, {5: [4], 4: [5]})
    assert [(r.chunk.chunk_id, r.via) for r in out] == [
        ("health-secure-plus-s5", "search"),
        ("health-secure-plus-s9", "search"),
        ("health-secure-plus-s4", "neighbour"),
    ]
    assert asked == [["health-secure-plus-s4"]]


def test_context_pack_dedupes_neighbour_already_hit() -> None:
    s5, s4 = chunk("Health Secure Plus", 5), chunk("Health Secure Plus", 4)
    out = context_pack(
        [hit(s5, 1), hit(s4, 2)], lambda ids: {s4.chunk_id: s4, s5.chunk_id: s5}, {5: [4], 4: [5]}
    )
    assert [r.chunk.chunk_id for r in out] == [s5.chunk_id, s4.chunk_id]
    assert all(r.via == "search" for r in out)


def test_context_pack_never_adds_neighbours_for_all_chunks() -> None:
    common = chunk("ALL", 5)
    out = context_pack([hit(common, 1)], lambda ids: pytest.fail("no lookup expected"), {5: [4]})
    assert [r.chunk.chunk_id for r in out] == ["all-s5"]


def test_sources_one_per_chunk_with_citation_label() -> None:
    hits = [hit(chunk("Health Secure Plus", 5, "Maternity"), 1), hit(chunk("ALL", 13, "Human Review"), 2)]
    sources = to_sources(hits)
    assert [s.label for s in sources] == [
        "[Health Secure Plus §5 Maternity]",
        "[All products §13 Human Review]",
    ]
    assert sources[0].kind == "policy" and sources[0].product == "Health Secure Plus"
    assert sources[0].section_no == 5 and sources[0].section_name == "Maternity"


def test_config_defaults_full_pipeline_with_rewrite_deferred() -> None:
    cfg = RetrievalConfig()
    assert cfg.use_dense and cfg.use_sparse and cfg.use_filter and cfg.use_rerank and cfg.use_glossary
    assert cfg.use_rewrite is False
