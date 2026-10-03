"""The clause slice against a private index of the real chunks (spec 11 metrics, config E)."""

from pathlib import Path

import pytest

from insurai.eval.retrieval import CONFIGS, load_policy_slice, run_config

# --- the real slice against a private index (slow: model inference over 35 queries × configs) ---


@pytest.mark.integration
@pytest.mark.slow
def test_AC_04_08_clause_slice_full_config_meets_targets(index_path: Path) -> None:
    summary = run_config(load_policy_slice(), CONFIGS["E"])["metrics"]
    assert summary["recall_at_5"] >= 0.95
    assert summary["product_precision_at_5"] >= 0.90
    assert summary["mrr"] >= 0.85


@pytest.mark.integration
@pytest.mark.slow
def test_AC_04_10_p95_latency_under_400ms(index_path: Path) -> None:
    summary = run_config(load_policy_slice(), CONFIGS["E"])["metrics"]
    assert summary["latency_p95_ms"] < 400


@pytest.mark.integration
@pytest.mark.slow
def test_AC_04_11_probes_not_confident_4_of_5_and_recall_holds(index_path: Path) -> None:
    result = run_config(load_policy_slice(), CONFIGS["E"])
    probes = [r for r in result["items"] if r["unanswerable"]]
    assert len(probes) == 5
    assert sum(not r["confident"] for r in probes) >= 4
    assert result["metrics"]["recall_at_5"] >= 0.95
