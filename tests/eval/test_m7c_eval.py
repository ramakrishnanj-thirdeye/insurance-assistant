"""Spec 11 (M7 fixes): judge robustness, guardrails V7 counts, advisory gating while the judge is
uncalibrated, the calibration tables and Part B re-score, and repeatable --slice. No LLM calls."""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from fakes import install

from insurai.eval import calibration, correctness, report, run
from insurai.eval import guardrails as guardrails_eval
from insurai.eval.baseline import advisory_keys, gate, open_gates
from insurai.settings import ROOT, get_settings

pytestmark = pytest.mark.unit

# The judge's sealed Part A scores from the first signed-off full run (eval/calibration/judge_scores.json is
# git-ignored; these are the values the calibration outcome was computed from).
JUDGE_SCORES = {
    "CAL01": 5,
    "CAL02": 1,
    "CAL03": 5,
    "CAL04": 5,
    "CAL05": 5,
    "CAL06": 5,
    "CAL07": 1,
    "CAL08": 5,
    "CAL09": 1,
    "CAL10": 2,
}


# --- AC-11-19 judge robustness ------------------------------------------------------------------------------


def test_AC_11_19_empty_judge_reason_is_retried_once(monkeypatch: pytest.MonkeyPatch) -> None:
    replies = iter([{"score": 5, "reason": "  "}, {"score": 4, "reason": "matches the gold"}])
    install(monkeypatch, {"CorrectnessScore": lambda m: next(replies)})
    rows = [{"id": "A", "answer": "an answer"}]
    correctness.judge_rows(rows, {"A": ("q", "g")})
    assert rows[0]["judge_score"] == 4 and rows[0]["judge_reason"] == "matches the gold"


def test_AC_11_19_empty_reason_twice_is_a_judge_error_excluded_from_correctness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reply(messages: list[Any]) -> dict[str, Any]:
        question = str(messages[0].content)
        return {"score": 5, "reason": "" if "broken answer" in question else "fine"}

    install(monkeypatch, {"CorrectnessScore": reply})
    rows = [{"id": "A", "answer": "good answer"}, {"id": "B", "answer": "broken answer"}]
    correctness.judge_rows(rows, {"A": ("q", "g"), "B": ("q", "g")})
    assert "judge_score" not in rows[1] and "judge_error" in rows[1]
    counts: dict[str, list[int]] = {}
    out = correctness.correctness_metrics(rows, counts)
    assert counts["correctness"] == [1, 1] and out["judge_errors"] == 1


# --- AC-11-20 guardrails V7 as k of n --------------------------------------------------------------------


def test_AC_11_20_guardrails_slice_reports_v7_faithfulness_as_k_of_n() -> None:
    judged = {"v7_passed": True, "v7_claims": 1, "v7_supported": 1, "v7_unsupported": [], "v7_verbatim": 1}
    rows = [{"id": i, "must_refuse": False, "refused": False, **judged} for i in ("G1", "G2")]
    counts: dict[str, list[int]] = {}
    metrics = guardrails_eval.metrics(rows, counts)
    assert metrics["faithfulness"] == 1.0 and counts["faithfulness"] == [2, 2]
    assert counts["v7_pass_rate"] == [2, 2]
    md = report.render({"slices": {"guardrails": {"metrics": metrics, "counts": counts}}})
    assert "| faithfulness | 2 of 2, " in md and "| v7_pass_rate | 2 of 2, " in md


# --- AC-11-21 calibration-aware gate and report ----------------------------------------------------------


def _uncalibrated_results() -> dict[str, Any]:
    return {
        "claim_analysis": {
            "metrics": {"correctness": 0.3, "faithfulness": 0.5, "rule_status_exact": 1.0},
            "counts": {"correctness": [3, 10], "faithfulness": [5, 10], "rule_status_exact": [10, 10]},
        }
    }


def test_AC_11_21_judge_metrics_are_advisory_while_uncalibrated() -> None:
    targets: dict[str, Any] = {
        "claim_analysis.correctness": 0.9,
        "claim_analysis.faithfulness": 0.95,
        "claim_analysis.rule_status_exact": 1.0,
    }
    advisory = advisory_keys(targets, ["correctness", "faithfulness"], calibrated=False)
    assert advisory == {"claim_analysis.correctness", "claim_analysis.faithfulness"}
    results = _uncalibrated_results()
    assert gate(results, None, targets, advisory) == []
    assert len(gate(results, None, targets, advisory_keys(targets, ["correctness"], calibrated=True))) == 2
    missed = open_gates(results, targets, advisory)
    assert {g["metric"] for g in missed if g.get("advisory")} == advisory
    md = report.render({"open_gates": missed, "gate": [], "slices": results})
    assert "## Advisory (judge uncalibrated, not gated)" in md and "Every gated target that ran is met." in md


def _real_calibration(tmp_path: Path) -> dict[str, Any]:
    cal_dir = tmp_path / "calibration"
    cal_dir.mkdir()
    shutil.copyfile(calibration.CAL_DIR / "items.json", cal_dir / "items.json")
    (cal_dir / "judge_scores.json").write_text(json.dumps(JUDGE_SCORES), encoding="utf-8")
    return calibration.status(calibration.CAL_MD, cal_dir)


def test_AC_11_21_calibration_outcome_on_the_signed_off_sheet(tmp_path: Path) -> None:
    state = _real_calibration(tmp_path)
    assert state["part_a"]["counts"] == [6, 10] and state["uncalibrated"]
    assert not calibration.is_calibrated(state)
    assert state["part_a"]["human_correct"] == [8, 10]
    assert state["part_b"]["counts"] == [3, 7]
    # the splitter fix: the table header (V7-02), the precedence sentence (V7-06) and the specialist-review
    # sentence (V7-07) no longer reach the judge; precision over the remaining flags is 3 of 4
    rows = {r["id"]: r for r in state["part_b"]["rows"]}
    assert {k for k, r in rows.items() if not r["reaches_judge"]} == {"V7-02", "V7-06", "V7-07"}
    assert state["part_b"]["dropped"] == [3, 7] and state["part_b"]["counts_after"] == [3, 4]
    lines = calibration.describe(state)
    assert any(line.startswith("Human-verified correctness on the calibration sample") and "8 of 10" in line
               for line in lines)  # fmt: skip
    assert any("**judge uncalibrated**" in line and "advisory, not gated" in line for line in lines)
    md = report.render({"calibration": state, "slices": {}})
    assert "## Judge calibration" in md and "| CAL02 | policy_clauses_e2e EVAL002 | 4 | 1 | no |" in md
    assert "| V7-02 | policy_clauses_e2e EVAL028 | Document Type \\| Description | unsupported |" in md


def test_AC_11_21_unscored_calibration_is_uncalibrated() -> None:
    assert not calibration.is_calibrated({"status": "no calibration file yet"})
    assert calibration.is_calibrated({"part_a": {"agreement": 0.8}})


def test_AC_11_21_settings_name_the_advisory_metrics() -> None:
    assert get_settings().eval.advisory_when_uncalibrated == ["correctness", "faithfulness"]
    assert get_settings().eval.targets["claim_analysis.orphan_numbers"] == {"max": 0}


# --- AC-11-22 repeatable --slice ----------------------------------------------------------------------------


def test_AC_11_22_slice_can_be_repeated_into_one_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ran: list[str] = []

    def stub(name: str) -> Any:
        def fn(**_: Any) -> dict[str, Any]:
            ran.append(name)
            return {
                "metrics": {"items": 1, "correctness": 0.1},
                "counts": {"correctness": [1, 10]},
                "items": [],
            }

        return fn

    monkeypatch.setattr(run, "ALL_SLICES", {name: stub(name) for name in run.ALL_SLICES})
    monkeypatch.setattr(calibration, "CAL_MD", tmp_path / "judge_calibration.md")
    monkeypatch.setattr(calibration, "CAL_DIR", tmp_path / "calibration")
    monkeypatch.setenv("INSURAI__PATHS__EVAL_REPORTS", str(tmp_path / "reports"))
    get_settings.cache_clear()
    try:
        argv = ["--suite", "full", "--slice", "claim_analysis", "--slice", "comparisons", "--gate"]
        assert run.main(argv) == 0  # correctness misses its target, but it is advisory: no calibration yet
    finally:
        get_settings.cache_clear()
    assert ran == ["claim_analysis", "comparisons"]
    (json_path,) = (tmp_path / "reports").glob("slice-claim_analysis+comparisons_*.json")
    body = json.loads(json_path.read_text(encoding="utf-8"))
    assert set(body["slices"]) == {"claim_analysis", "comparisons"}
    assert "claim_analysis.correctness" in body["advisory"] and body["gate"] == []


def test_calibration_items_file_is_tracked() -> None:
    assert (ROOT / "eval" / "calibration" / "items.json").exists()
