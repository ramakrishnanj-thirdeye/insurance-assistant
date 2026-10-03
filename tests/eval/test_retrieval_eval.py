"""Retrieval eval: metrics (spec 11 definitions), configs A–E, threshold tuning and the slice gates."""

import json
from datetime import date
from pathlib import Path

import pytest
from insurai.eval.retrieval import (
    CONFIGS,
    EvalItem,
    load_policy_slice,
    mrr,
    product_precision_at_k,
    recall_at_k,
    run_ablation,
    tune_threshold,
)

from insurai.knowledge.parse import citation_label, slug
from insurai.knowledge.schemas import PolicyChunk
from insurai.retrieval.schemas import RetrievalConfig, RetrievalResult, RetrievedChunk
from insurai.settings import ROOT
from insurai.tools.schemas import ToolContext

ADR_002 = ROOT / "decisions" / "ADR-002-qdrant-embedded.md"


def _chunk(product: str, section_no: int, name: str) -> PolicyChunk:
    common = product == "ALL"
    return PolicyChunk(
        chunk_id=f"all-s{section_no}" if common else f"{slug(product)}-s{section_no}",
        product=product,
        policy_type=None if common else "Health",
        section_no=section_no,
        section_name=name,
        is_common=common,
        text="t",
        header="h",
        embed_text="h: t",
        citation_label=citation_label(product, section_no, name),
        content_hash="c",
        source_path="p",
    )


@pytest.mark.unit
def test_metrics_follow_spec_11_definitions() -> None:
    labels = ["[A §1 X]", "[B §2 Y]", "[C §3 Z]"]
    assert recall_at_k(labels, ["B §2 Y"], k=5) == 1.0
    assert recall_at_k(labels, ["B §2 Y"], k=1) == 0.0
    assert mrr(labels, ["C §3 Z", "B §2 Y"]) == pytest.approx(0.5)
    assert mrr(labels, ["Q §9 W"]) == 0.0
    assert product_precision_at_k(["A", "ALL", "B", "A"], "A", k=5) == pytest.approx(0.75)
    assert product_precision_at_k([], "A", k=5) == 0.0


@pytest.mark.unit
def test_slice_has_30_answerable_and_5_probes_with_real_labels() -> None:
    items = load_policy_slice()
    answerable = [i for i in items if not i.unanswerable]
    probes = [i for i in items if i.unanswerable]
    assert (len(answerable), len(probes)) == (30, 5)
    assert {f"EVAL00{n}" for n in range(1, 6)} <= {i.id for i in items}
    from insurai.knowledge.parse import build_chunks, parse_corpus
    from insurai.settings import get_settings

    real = {
        c.citation_label.strip("[]") for c in build_chunks(parse_corpus(get_settings().paths.policy_docs_dir))
    }
    for item in answerable:
        assert item.gold_sources and set(item.gold_sources) <= real, item.id
        assert item.product
    common = [i for i in answerable if all(s.startswith("All products") for s in i.gold_sources)]
    assert len(common) >= 3
    assert all(not p.gold_sources and p.product is None for p in probes)


@pytest.mark.unit
def test_AC_04_11_threshold_sweep_maximises_f1() -> None:
    threshold, f1 = tune_threshold(answerable=[2.0, 3.0, 1.5, 4.0], unanswerable=[-3.0, -1.0, 0.5])
    assert 0.5 < threshold <= 1.5
    assert f1 == pytest.approx(1.0)


@pytest.mark.unit
def test_AC_04_09_ablation_report_has_configs_A_to_E(tmp_path: Path) -> None:
    gold = _chunk("Health Secure Plus", 5, "Maternity")
    other = _chunk("Two Wheeler Secure", 9, "Exclusions")

    def fake_search(
        ctx: ToolContext, query: str, product: str | None, cfg: RetrievalConfig
    ) -> RetrievalResult:
        order = [gold, other] if cfg.use_filter else [other, gold]
        chunks = [
            RetrievedChunk(chunk=c, fused_rank=i + 1, rerank_score=1.0 - i, boosted=False, via="search")
            for i, c in enumerate(order)
        ]
        return RetrievalResult(
            query=query, rewritten_query=query, filters={}, section_hints=[], chunks=chunks,
            confident=True, timings_ms={"total": 10.0}, sources=[],
        )  # fmt: skip

    items = [
        EvalItem(
            id="E1",
            question="q",
            product="Health Secure Plus",
            gold_sources=["Health Secure Plus §5 Maternity"],
        ),
        EvalItem(id="E2", question="space", product=None, gold_sources=[], unanswerable=True),
    ]
    path = run_ablation(items, search_fn=fake_search, out_dir=tmp_path, as_of=date(2026, 10, 1))
    assert path.name.startswith("ablation_") and path.suffix == ".json"
    report = json.loads(path.read_text(encoding="utf-8"))
    assert list(report["configs"]) == ["A", "B", "C", "D", "E"]
    for summary in report["configs"].values():
        assert {"recall_at_5", "product_precision_at_5", "mrr", "latency_p50_ms", "latency_p95_ms"} <= set(
            summary["metrics"]
        )
    assert report["configs"]["D"]["metrics"]["mrr"] == 1.0
    assert report["configs"]["A"]["metrics"]["mrr"] == 0.5
    assert report["deferred"] == ["F (+rewrite): 3-day scope"]


@pytest.mark.unit
def test_configs_are_cumulative_and_glossary_always_on() -> None:
    assert list(CONFIGS) == ["A", "B", "C", "D", "E"]
    a, b, c, d, e = CONFIGS.values()
    assert (a.use_dense, a.use_sparse) == (True, False)
    assert (b.use_dense, b.use_sparse) == (False, True)
    assert (c.use_dense, c.use_sparse, c.use_filter) == (True, True, False)
    assert d.use_filter and not d.use_rerank
    assert e.use_filter and e.use_rerank
    assert all(cfg.use_glossary and not cfg.use_rewrite for cfg in CONFIGS.values())


@pytest.mark.unit
def test_AC_04_01_adr_records_spike_outcome() -> None:
    text = ADR_002.read_text(encoding="utf-8")
    assert "Status: accepted" in text
    outcome = text.split("**Spike outcome.**", 1)[1]
    assert "M2 spike" in outcome and "p95" in outcome and "recall@5" in outcome
