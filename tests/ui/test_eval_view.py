"""Eval Dashboard helpers (spec 10, AC-10-11): metrics vs targets with k of n and intervals, gates,
calibration, ablation, history and failed items."""

import pytest
from eval_view import (
    ablation_rows,
    calibration_rows,
    default_run,
    failed_items,
    gate_rows,
    history_rows,
    metric_rows,
    run_label,
)

pytestmark = pytest.mark.unit

REPORT = {
    "suite": "full",
    "advisory": ["claim_analysis.correctness"],
    "open_gates": [
        {"metric": "analytics.exec_accuracy", "value": 0.6667, "target": "min 0.9", "counts": [10, 15]},
        {
            "metric": "claim_analysis.correctness",
            "value": 0.5,
            "target": "min 0.9",
            "counts": [5, 10],
            "advisory": True,
        },
    ],
    "calibration": {
        "part_a": {
            "status": "scored",
            "counts": [6, 10],
            "rows": [
                {"id": "CAL01", "item": "policy_clauses_e2e EVAL008", "human": 4, "judge": 5, "agree": True}
            ],
        },
        "part_b": {
            "status": "scored",
            "counts": [3, 7],
            "sampled": 7,
            "total": 7,
            "rows": [
                {
                    "id": "CAL11",
                    "item": "claim_analysis CA006",
                    "claim": "Untracked documents: none.",
                    "verdict": "unsupported",
                    "human": "false positive",
                    "agree": False,
                    "reaches_judge": False,
                }
            ],
        },
    },
    "slices": {
        "analytics": {
            "metrics": {"exec_accuracy": 0.6667, "wrong": ["ANA003"]},
            "counts": {"exec_accuracy": [10, 15]},
            "items": [{"id": "ANA003", "gold_rows": [[1]], "rows": [[2]], "reason": "extra column"}],
        },
        "claim_analysis": {"metrics": {"correctness": 0.5}, "counts": {"correctness": [5, 10]}, "items": []},
        "suite": {"metrics": {"false_refusal": 0.0}, "counts": {"false_refusal": [0, 44]}},
    },
    "questions": {"ANA003": "Average claim amount by hospital?"},
}
TARGETS = {
    "analytics.exec_accuracy": 0.9,
    "claim_analysis.correctness": 0.9,
    "suite.false_refusal": {"max": 0.05},
    "sql_facts.accuracy": 1.0,
}


def test_AC_10_11_metric_rows_value_k_of_n_interval_target_status() -> None:
    rows = {r["metric"]: r for r in metric_rows(REPORT, TARGETS)}
    exec_row = rows["analytics.exec_accuracy"]
    assert exec_row["k of n"] == "10 of 15" and exec_row["95% interval"] == "0.42–0.85"
    assert exec_row["target"] == "≥ 0.9" and exec_row["status"] == "✗ open"
    assert rows["claim_analysis.correctness"]["status"] == "advisory (judge uncalibrated)"
    assert (
        rows["suite.false_refusal"]["status"] == "✓ met" and rows["suite.false_refusal"]["target"] == "≤ 0.05"
    )
    assert rows["sql_facts.accuracy"]["status"] == "not run"


def test_AC_10_11_open_gates_and_advisory_sections() -> None:
    assert gate_rows(REPORT, advisory=False) == [
        {"metric": "analytics.exec_accuracy", "value": "10 of 15, 0.42–0.85", "target": "min 0.9"}
    ]
    assert [r["metric"] for r in gate_rows(REPORT, advisory=True)] == ["claim_analysis.correctness"]


def test_AC_10_11_both_calibration_tables() -> None:
    part_a, part_b = calibration_rows(REPORT)
    assert part_a == [
        {"id": "CAL01", "item": "policy_clauses_e2e EVAL008", "human": 4, "judge": 5, "agree": "yes"}
    ]
    assert part_b[0]["human"] == "false positive" and part_b[0]["still reaches the judge"] == "no"
    assert calibration_rows({}) == ([], [])


def test_AC_10_11_failed_items_with_question_expected_and_actual() -> None:
    assert failed_items(REPORT) == [
        {
            "slice": "analytics",
            "id": "ANA003",
            "question": "Average claim amount by hospital?",
            "expected": "[[1]]",
            "actual": "[[2]]",
            "judge reason": "",
        }
    ]


def test_AC_10_11_ablation_rows_for_configs_a_to_e() -> None:
    report = {
        "configs": {
            c: {"description": d, "metrics": {"recall_at_5": 1.0, "product_precision_at_5": p, "mrr": 0.9}}
            for c, d, p in (("A", "dense-only", 0.69), ("D", "+filter", 1.0), ("E", "+rerank", 1.0))
        }
    }
    rows = ablation_rows(report)
    assert {r["metric"] for r in rows} == {"recall@5", "product precision@5"}
    assert rows[0] == {"config": "A dense-only", "metric": "recall@5", "value": 1.0}
    assert len(rows) == 6


def test_AC_10_11_history_oldest_first_without_baseline_or_ablation() -> None:
    summaries = [
        {
            "run_id": "fast_2",
            "suite": "fast",
            "created_at": "2026-10-09",
            "headline": {"routing": {"intent_accuracy": 0.97}},
        },
        {
            "run_id": "baseline",
            "suite": "full",
            "baseline_of": "full_1.json",
            "created_at": "2026-10-08",
            "headline": {"routing": {"intent_accuracy": 0.96}},
        },
        {"run_id": "ablation_1", "suite": "ablation", "created_at": "2026-10-08", "headline": {}},
        {
            "run_id": "fast_1",
            "suite": "fast",
            "created_at": "2026-10-05",
            "headline": {"routing": {"intent_accuracy": 0.91}},
        },
    ]
    rows = history_rows(summaries, ["routing.intent_accuracy"])
    assert [r["run"] for r in rows] == ["fast_1", "fast_2"] and rows[0]["value"] == 0.91
    assert default_run(summaries[2:]) == 1  # skips the ablation run
    assert run_label(summaries[1]).startswith("baseline (full_1)")
