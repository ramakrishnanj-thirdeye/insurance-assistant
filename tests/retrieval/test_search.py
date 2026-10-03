"""search_policy and similar_sql_examples against a private index of the real chunks."""

from pathlib import Path

import pytest
from insurai.retrieval.schemas import RetrievalConfig
from insurai.retrieval.search import search_policy, similar_sql_examples

from insurai.tools.schemas import ToolContext

pytestmark = pytest.mark.integration

PRODUCTS = [
    "Health Secure Plus",
    "Family Care Gold",
    "Critical Care Elite",
    "Maternity Protect",
    "Senior Health Shield",
    "Car Shield Plus",
    "Motor Protect Comprehensive",
    "Two Wheeler Secure",
    "Global Travel Secure",
    "Student Travel Protect",
]
QUERIES = ["What is excluded?", "What is the waiting period?", "How do I make a claim?"]


def _labels(result) -> list[str]:  # type: ignore[no-untyped-def]
    return [r.chunk.citation_label for r in result.chunks if r.via == "search"]


def test_AC_04_04_eval001_maternity_in_top3(index_path: Path, ctx: ToolContext) -> None:
    result = search_policy(
        ctx, "Under Health Secure Plus, what is the maternity waiting period?", product="Health Secure Plus"
    )
    assert "[Health Secure Plus §5 Maternity]" in _labels(result)[:3]


def test_AC_04_05_eval004_mpc_exclusions_top1_no_two_wheeler(index_path: Path, ctx: ToolContext) -> None:
    result = search_policy(
        ctx,
        "Under Motor Protect Comprehensive, is drunk driving covered?",
        product="Motor Protect Comprehensive",
    )
    assert _labels(result)[0] == "[Motor Protect Comprehensive §9 Exclusions]"
    assert all(r.chunk.product != "Two Wheeler Secure" for r in result.chunks)


@pytest.mark.parametrize("product", PRODUCTS)
def test_AC_04_06_product_filter_returns_only_product_or_all(
    index_path: Path, ctx: ToolContext, product: str
) -> None:
    for query in QUERIES:
        result = search_policy(ctx, query, product=product)
        assert result.chunks
        assert {r.chunk.product for r in result.chunks} <= {product, "ALL"}
        assert result.filters == {"product": [product, "ALL"]} and not result.unfiltered


def test_AC_04_06_policy_type_filter_returns_type_or_common(index_path: Path, ctx: ToolContext) -> None:
    result = search_policy(ctx, "What is excluded?", policy_type="Travel")
    assert all(r.chunk.policy_type == "Travel" or r.chunk.is_common for r in result.chunks)


def test_result_shape_sources_timings_hints(index_path: Path, ctx: ToolContext) -> None:
    result = search_policy(ctx, "Is pregnancy covered?", product="Family Care Gold")
    assert result.section_hints[:2] == [5, 4]
    assert "maternity" in result.rewritten_query
    assert [s.label for s in result.sources] == [r.chunk.citation_label for r in result.chunks]
    assert {"glossary", "embed", "search", "rerank", "pack", "total"} <= set(result.timings_ms)
    assert sum(r.via == "search" for r in result.chunks) <= 5


def test_neighbour_section_4_packed_with_section_5(index_path: Path, ctx: ToolContext) -> None:
    result = search_policy(ctx, "maternity waiting period", product="Health Secure Plus")
    ids = [r.chunk.chunk_id for r in result.chunks]
    assert "health-secure-plus-s5" in ids and "health-secure-plus-s4" in ids
    assert len(ids) == len(set(ids))


def test_no_product_is_flagged_unfiltered(index_path: Path, ctx: ToolContext) -> None:
    result = search_policy(ctx, "Is drunk driving covered?")
    assert result.unfiltered and result.filters == {}


@pytest.mark.parametrize(
    "cfg",
    [
        RetrievalConfig(use_sparse=False, use_filter=False, use_rerank=False),
        RetrievalConfig(use_dense=False, use_filter=False, use_rerank=False),
        RetrievalConfig(use_glossary=False),
    ],
    ids=["dense-only", "bm25-only", "no-glossary"],
)
def test_ablation_switches_still_return_chunks(
    index_path: Path, ctx: ToolContext, cfg: RetrievalConfig
) -> None:
    result = search_policy(ctx, "Is dental treatment covered?", product="Family Care Gold", cfg=cfg)
    assert result.chunks


def test_rewrite_switch_is_deferred(index_path: Path, ctx: ToolContext) -> None:
    with pytest.raises(NotImplementedError, match="deferred"):
        search_policy(ctx, "x", cfg=RetrievalConfig(use_rewrite=True))


def test_similar_sql_examples_returns_verified_queries(index_path: Path) -> None:
    examples = similar_sql_examples("How many claims are pending documents?", k=3)
    assert len(examples) == 3
    assert examples[0].name == "pending_documents_count"
    assert examples[0].sql.startswith("SELECT")
