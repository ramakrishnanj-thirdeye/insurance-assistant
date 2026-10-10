"""Routing rule 2, common sections (spec 06, AC-06-26; prompted by EVAL036): a confident common (ALL) chunk
anywhere in the unfiltered probe's top 3 answers from the common sections instead of asking for a product."""

from datetime import date
from typing import Any

import pytest
from fakes import plan_of

from insurai.agent.graph import _product_probe
from insurai.agent.planner import PlanContext, finalize_plan
from insurai.agent.routing import probe_outcome
from insurai.agent.schemas import Entities, Intent
from insurai.agent.workers import policy_rag
from insurai.knowledge.schemas import PolicyChunk
from insurai.retrieval.schemas import RetrievalResult, RetrievedChunk
from insurai.tools.registry import TOOLS
from insurai.tools.schemas import ToolContext

CASHLESS = "Is a cashless approval at a network hospital the same as a final settlement?"
WAITING = "What is the waiting period?"
THRESHOLD = -4.66


def _chunk(product: str, section_no: int, section_name: str, score: float | None, via: str = "search") -> Any:
    owner = "All products" if product == "ALL" else product
    chunk = PolicyChunk(
        chunk_id=f"{product.lower().replace(' ', '-')}-s{section_no}",
        product=product,
        policy_type=None if product == "ALL" else "Health",
        section_no=section_no,
        section_name=section_name,
        is_common=product == "ALL",
        text=f"{section_name} wording.",
        header=f"{owner} › §{section_no} {section_name}",
        embed_text=f"{section_name} wording.",
        citation_label=f"[{owner} §{section_no} {section_name}]",
        content_hash="h",
        source_path="p",
    )
    return RetrievedChunk(chunk=chunk, fused_rank=1, rerank_score=score, boosted=False, via=via)  # type: ignore[arg-type]


def _result(*chunks: RetrievedChunk, confident: bool = True) -> RetrievalResult:
    from insurai.retrieval.search import to_sources

    return RetrievalResult(
        query="q",
        rewritten_query="q",
        filters={},
        section_hints=[],
        chunks=list(chunks),
        confident=confident,
        timings_ms={},
        sources=to_sources(list(chunks)),
        unfiltered=True,
    )


PRODUCT_TOP = _chunk("Health Secure Plus", 6, "Claim Settlement", 1.2)
COMMON_7 = _chunk("ALL", 7, "Cashless / Network Process", 0.4)
CASHLESS_PROBE = _result(PRODUCT_TOP, COMMON_7, _chunk("Senior Health Shield", 6, "Claim Settlement", 0.1))
WAITING_PROBE = _result(
    _chunk("Health Secure Plus", 3, "Waiting Period", 2.0),
    _chunk("Senior Health Shield", 3, "Waiting Period", 1.9),
    _chunk("Family Care Gold", 3, "Waiting Period", 1.8),
    _chunk("ALL", 13, "Human Review", 1.0),
)


@pytest.mark.unit
def test_AC_06_26_probe_common_chunk_in_top_3_is_common() -> None:
    assert probe_outcome(CASHLESS_PROBE, THRESHOLD, 3) == "common"


@pytest.mark.unit
def test_AC_06_26_probe_common_chunk_below_top_3_or_threshold_is_product() -> None:
    assert probe_outcome(WAITING_PROBE, THRESHOLD, 3) == "product"  # ALL at rank 4
    weak = _result(PRODUCT_TOP, _chunk("ALL", 7, "Cashless / Network Process", -6.0))
    assert probe_outcome(weak, THRESHOLD, 3) == "product"
    neighbour = _result(PRODUCT_TOP, _chunk("ALL", 7, "Cashless / Network Process", None, via="neighbour"))
    assert probe_outcome(neighbour, THRESHOLD, 3) == "product"  # only ranked search hits count


@pytest.mark.unit
def test_AC_06_26_probe_not_confident_is_none() -> None:
    assert probe_outcome(_result(COMMON_7, confident=False), THRESHOLD, 3) == "none"
    assert probe_outcome(_result(confident=False), THRESHOLD, 3) == "none"


def _plan(message: str, probe: RetrievalResult) -> Any:
    return finalize_plan(
        plan_of(("policy_question", {}), question=message),
        PlanContext(
            persona="claims_agent",
            principal_id=None,
            message=message,
            resolved=Entities(),
            active=Entities(),
            max_intents=3,
            product_probe=lambda q: probe_outcome(probe, THRESHOLD, 3),
        ),
    )


@pytest.mark.unit
def test_AC_06_26_cashless_versus_settlement_answers_from_section_7(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan(CASHLESS, CASHLESS_PROBE)
    assert plan.clarification is None
    [intent] = plan.intents
    assert (intent.type, intent.entities.product, intent.common_only) == ("policy_question", None, True)

    monkeypatch.setitem(TOOLS, "search_policy", lambda ctx, **kw: CASHLESS_PROBE)
    out = policy_rag(
        {"intent": intent, "persona": "claims_agent", "principal_id": None, "turn": 1, "trace_id": "t"}
    )
    [ev] = out["evidence"]
    assert [c["label"] for c in ev.payload["clauses"]] == ["[All products §7 Cashless / Network Process]"]
    assert [s.label for s in ev.sources] == ["[All products §7 Cashless / Network Process]"]
    assert "Health Secure Plus" not in ev.summary


@pytest.mark.unit
def test_AC_06_26_waiting_period_still_asks_which_product() -> None:
    plan = _plan(WAITING, WAITING_PROBE)
    assert plan.intents == [] and plan.clarification is not None
    assert plan.clarification.startswith("Which product")


@pytest.mark.unit
def test_AC_06_26_product_questions_keep_every_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    intent = Intent(
        id="i1", type="policy_question", entities=Entities(product="Health Secure Plus"), sub_question="q"
    )
    monkeypatch.setitem(TOOLS, "search_policy", lambda ctx, **kw: CASHLESS_PROBE)
    out = policy_rag(
        {"intent": intent, "persona": "claims_agent", "principal_id": None, "turn": 1, "trace_id": "t"}
    )
    assert len(out["evidence"][0].payload["clauses"]) == 3


def _ctx() -> ToolContext:
    return ToolContext(persona="claims_agent", as_of=date(2026, 10, 1), trace_id="t-ac-06-26")


@pytest.mark.integration
def test_AC_06_26_real_index_cashless_probes_common(index_path: Any) -> None:
    assert _product_probe(_ctx(), CASHLESS) == "common"
    result = TOOLS["search_policy"](_ctx(), CASHLESS)
    top3 = [c.chunk.citation_label for c in result.chunks if c.via == "search"][:3]
    assert "[All products §7 Cashless / Network Process]" in top3


@pytest.mark.integration
def test_AC_06_26_real_index_waiting_period_probes_product(index_path: Any) -> None:
    assert _product_probe(_ctx(), WAITING) == "product"
