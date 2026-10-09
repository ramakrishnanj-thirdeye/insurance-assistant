"""Policy-knowledge tools: search_policy (spec 04) and get_coverage (spec 03) behind the persona gate."""

from functools import lru_cache
from typing import get_args

from insurai.knowledge import coverage
from insurai.knowledge.schemas import CoverageCell, PolicyType
from insurai.retrieval import search
from insurai.retrieval.schemas import RetrievalResult
from insurai.tools.base import tool
from insurai.tools.schemas import AccessDenied, NotFound, SourceRef, ToolContext, ToolResult

POLICY_TYPES: list[str] = list(get_args(PolicyType))


class CoverageCells(ToolResult):
    product: str | None
    attribute: str | None
    cells: list[CoverageCell]


@tool
def search_policy(
    ctx: ToolContext,
    query: str,
    product: str | None = None,
    policy_type: str | None = None,
    section_hints: list[int] | None = None,
    pinned_sections: list[int] | None = None,
) -> RetrievalResult | NotFound | AccessDenied:
    """Search the policy wordings (hybrid retrieval, product-filtered) and return cited clauses.
    `pinned_sections` are added by chunk id, unranked (spec 08 guarantee requests: §14, §15)."""
    if not query.strip():
        return NotFound(entity="query", message="Ask a question about the policy wording.")
    if product is not None:
        canonical = _products().get(product.strip().lower())
        if canonical is None:
            return _unknown_product(product)
        product = canonical
    if policy_type is not None and policy_type not in POLICY_TYPES:
        return NotFound(
            entity="policy_type", message=f"Unknown policy type {policy_type!r}; expected {POLICY_TYPES}."
        )
    return search.search_policy(
        ctx,
        query,
        product=product,
        policy_type=policy_type,
        section_hints=section_hints,
        pinned_sections=pinned_sections,
    )


@tool
def get_coverage(
    ctx: ToolContext, product: str | None = None, attribute: str | None = None
) -> CoverageCells | NotFound | AccessDenied:
    """Coverage matrix cells (sum insured, waiting period, maternity, exclusions, claim procedure), cited."""
    if product is not None and product.strip().lower() not in _products():
        return _unknown_product(product)
    try:
        cells = coverage.get_coverage(product, attribute)
    except ValueError as exc:
        return NotFound(entity="attribute", message=str(exc))
    refs: dict[str, SourceRef] = {}
    for cell in cells:
        for ref in cell.sources:
            refs.setdefault(ref.label, ref)
    return CoverageCells(product=product, attribute=attribute, cells=cells, sources=list(refs.values()))


@lru_cache(maxsize=1)
def _products() -> dict[str, str]:
    return {p.lower(): p for p in coverage.load_coverage(coverage.COVERAGE_FILE).products}


def _unknown_product(product: str) -> NotFound:
    return NotFound(
        entity="product",
        message=f"Unknown product {product!r}; expected one of {sorted(_products().values())}.",
    )
