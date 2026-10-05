"""claim_analysis eval slice (spec 11 metrics for spec 07): scripted narrator and judge, real warehouse."""

import json
import re
from typing import Any

import pytest
from fakes import install

from insurai.eval import claim_analysis
from insurai.eval.run import gate
from insurai.settings import get_settings

pytestmark = pytest.mark.integration


@pytest.fixture
def warehouse_ready() -> None:
    if not get_settings().paths.warehouse.exists():
        pytest.skip("data/warehouse.duckdb not built: run `make data`")


def _narrator(messages: list[Any]) -> str:
    system = str(messages[0].content)
    if "<draft>" in system:
        return re.search(r"<draft>(.*)</draft>", system, re.DOTALL).group(1)  # type: ignore[union-attr]
    data = json.loads(re.search(r"<assessment>(.*)</assessment>", system, re.DOTALL).group(1))  # type: ignore[union-attr]
    return f"Position. {data['label']}"  # the completeness guard adds every finding and action


def test_slice_scores_rules_interrupts_mentions_and_judge(
    warehouse_ready: None, index_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch, {"Text": _narrator, "InventedFindings": lambda m: {"invented": [], "count": 0}})
    result = claim_analysis.run_slice()
    m = result["metrics"]
    assert m["items"] == len(claim_analysis.load_items()) >= 10 and m["draft_items"] == 0
    assert (
        m["rule_status_exact"] == m["docs_exact"] == m["consistency_exact"] == m["needs_review_exact"] == 1.0
    )
    assert m["review_interrupt"] == 1.0 and m["blocker_mention"] == 1.0
    assert m["invented_findings"] == 0 and m["invented_findings_free"] == 1.0 and m["wrong"] == []
    rows = {r["id"]: r for r in result["items"]}
    assert claim_analysis.expected_interrupt(claim_analysis.load_items()[0])  # CA001 assesses
    assert not any(
        claim_analysis.expected_interrupt(i) for i in claim_analysis.load_items() if i.id == "CA010"
    )  # the control explains
    assert rows["CA001"]["narrative"]
    targets = {k: v for k, v in get_settings().eval.targets.items() if k.startswith("claim_analysis.")}
    assert len(targets) == 4 and gate({"claim_analysis": result}, targets) == []


def test_judged_inventions_fail_the_gate(
    warehouse_ready: None, index_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(
        monkeypatch,
        {"Text": _narrator, "InventedFindings": lambda m: {"invented": ["a fraud flag"], "count": 1}},
    )
    monkeypatch.setattr(claim_analysis, "SOURCES", ("claim_analysis_seed.jsonl",))
    result = claim_analysis.run_slice()
    assert result["metrics"]["invented_findings"] == 3 and result["metrics"]["invented_findings_free"] == 0.0
    failures = gate({"claim_analysis": result}, get_settings().eval.targets)
    assert any(f.startswith("claim_analysis.invented_findings_free") for f in failures)


def test_judge_calls_run_after_every_narrative(
    warehouse_ready: None, index_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-006 amendment: one phase of generation, then one phase of judging (no model swap per item)."""
    calls: list[str] = []

    def narrator(messages: list[Any]) -> str:
        calls.append("judge" if "<narrative>" in str(messages[0].content) else "generate")
        return _narrator(messages)

    def judge(messages: list[Any]) -> dict[str, Any]:
        calls.append("judge")
        return {"invented": [], "count": 0}

    install(monkeypatch, {"Text": narrator, "InventedFindings": judge})
    monkeypatch.setattr(claim_analysis, "SOURCES", ("claim_analysis_seed.jsonl",))
    claim_analysis.run_slice()
    first_judge = calls.index("judge")
    assert "generate" not in calls[first_judge:] and calls.count("judge") == 3
