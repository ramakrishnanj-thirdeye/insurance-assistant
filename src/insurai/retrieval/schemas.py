"""Retrieval models (spec 04 Interfaces)."""

from typing import Literal

from pydantic import BaseModel, Field

from insurai.knowledge.schemas import PolicyChunk
from insurai.settings import get_settings
from insurai.tools.schemas import SourceRef


class RetrievalConfig(BaseModel):
    """Ablation switches; defaults = the full pipeline in scope.

    `use_rewrite` (LLM rewrite, stage 2) is deferred for the 3-day delivery, so it defaults to False.
    """

    use_dense: bool = True
    use_sparse: bool = True
    use_filter: bool = True
    use_rerank: bool = True
    use_rewrite: bool = False
    use_glossary: bool = True
    prefetch_k: int = Field(default_factory=lambda: get_settings().retrieval.prefetch_k)
    final_k: int = Field(default_factory=lambda: get_settings().retrieval.final_k)


class RetrievedChunk(BaseModel):
    chunk: PolicyChunk
    fused_rank: int  # 1-based rank after fusion (or after the single retriever)
    rerank_score: float | None  # cross-encoder score plus any section boost; None without rerank
    boosted: bool
    via: Literal["search", "neighbour", "pinned"]


class RetrievalResult(BaseModel):
    query: str
    rewritten_query: str
    filters: dict
    section_hints: list[int]
    chunks: list[RetrievedChunk]
    confident: bool
    timings_ms: dict[str, float]
    sources: list[SourceRef]
    unfiltered: bool = False  # no product or policy type to filter on; spec 06 may ask for a product


class IndexReport(BaseModel):
    collection: str
    points: int
    seconds: float
    models: list[str]
