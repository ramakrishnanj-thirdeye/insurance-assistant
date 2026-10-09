"""Eval runner (spec 11).

Slices: policy_clauses (retrieval), sql_facts (tools), routing (planner, spec 06), e2e_sql_facts (full
graph), claim_analysis (rules engine and dossier, spec 07), analytics (run_analytics against gold SQL,
spec 02) and guardrails (spec 08) make up `--suite fast`. `--suite full` adds the full-graph slices with the
correctness judge: policy_clauses_e2e, comparisons and adversarial; then the suite-level false_refusal and
the judge calibration (eval/calibration.py, built on the first full run).

Every run writes eval/reports/<suite>_<ts>.json and .md. The gate (insurai.eval.baseline) compares target
metrics with eval/reports/baseline.json; `--gate` exits 1 on a failure. `--sample N` runs a seeded N-item
subset of the routing slice (development smoke).
"""

import argparse
from collections.abc import Callable
from typing import Any

import yaml

from insurai.eval import (
    adversarial,
    analytics,
    calibration,
    claim_analysis,
    e2e,
    e2e_sql_facts,
    guardrails,
    routing,
    sql_facts,
)
from insurai.eval.baseline import gate, load_baseline, open_gates
from insurai.eval.counts import derive_counts
from insurai.eval.retrieval import (
    CONFIGS,
    SLICE,
    UNANSWERABLE,
    load_policy_slice,
    run_ablation,
    run_config,
    write_report,
)
from insurai.eval.stats import count, prop
from insurai.observability import get_logger
from insurai.retrieval import search
from insurai.settings import ROOT, get_settings

log = get_logger(__name__)

SLICES: dict[str, Callable[..., dict[str, Any]]] = {
    SLICE: lambda: run_config(load_policy_slice(), CONFIGS["E"]),
    sql_facts.SLICE: sql_facts.run_slice,
    routing.SLICE: routing.run_slice,
    e2e_sql_facts.SLICE: e2e_sql_facts.run_slice,
    claim_analysis.SLICE: claim_analysis.run_slice,
    analytics.SLICE: analytics.run_slice,
    guardrails.SLICE: guardrails.run_slice,
}
FULL_ONLY: dict[str, Callable[..., dict[str, Any]]] = {
    e2e.CLAUSES_SLICE: e2e.run_clauses,
    e2e.COMPARISONS_SLICE: e2e.run_comparisons,
    adversarial.SLICE: adversarial.run_slice,
}
ALL_SLICES = SLICES | FULL_ONLY
SUITE = "suite"  # pseudo-slice for metrics across slices
# Non-adversarial slices whose answerable items count towards false_refusal (spec 11).
FALSE_REFUSAL_SLICES = (e2e.CLAUSES_SLICE, e2e.COMPARISONS_SLICE, e2e_sql_facts.SLICE, guardrails.SLICE)


def suite_metrics(results: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """false_refusal: answerable items of the non-adversarial full-graph slices that were refused
    (unanswerable probes excluded: abstaining is their right answer)."""
    rows = [
        r
        for name in FALSE_REFUSAL_SLICES
        for r in results.get(name, {}).get("items", [])
        if "error" not in r and not r.get("must_refuse") and UNANSWERABLE not in (r.get("tags") or [])
    ]
    if not rows:
        return None
    metrics: dict[str, Any] = {}
    counts: dict[str, list[int]] = {}
    prop(metrics, counts, "false_refusal", *count(bool(r.get("refused")) for r in rows))
    metrics["refused_items"] = [r["id"] for r in rows if r.get("refused")]
    return {"metrics": metrics, "counts": counts}


def coverage_status() -> str:
    path = ROOT / "config" / "coverage_matrix.yaml"
    return str(yaml.safe_load(path.read_text(encoding="utf-8")).get("status", "unknown"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="insurai.eval.run")
    parser.add_argument("--suite", choices=["fast", "full", "ablation"], required=True)
    parser.add_argument("--slice", dest="slice_name", choices=sorted(ALL_SLICES))
    parser.add_argument("--gate", action="store_true", help="exit 1 when the gate fails")
    parser.add_argument("--sample", type=int, help="routing only: score a seeded subset of N items")
    args = parser.parse_args(argv)

    if args.suite == "ablation":
        run_ablation(load_policy_slice())
        return 0
    if args.slice_name:
        names = [args.slice_name]
    else:
        names = list(SLICES) if args.suite == "fast" else list(ALL_SLICES)

    results: dict[str, dict[str, Any]] = {}
    for name in names:
        results[name] = ALL_SLICES[name](sample=args.sample) if name == routing.SLICE else ALL_SLICES[name]()
        log.info("%s: %s", name, results[name]["metrics"])
    if suite := suite_metrics(results):
        results[SUITE] = suite
    for name, result in results.items():
        result["counts"] = derive_counts(name, result)

    cal_state: dict[str, Any] = {}
    if args.suite == "full" and not args.slice_name:
        calibration.build(results)
        calibration.judge_part_a()
        cal_state = calibration.status()
    calibration.seal(results)  # per-item judge scores of calibration items stay hidden until scored

    targets = get_settings().eval.targets
    failures = gate(results, load_baseline(), targets)
    write_report(
        f"slice-{args.slice_name}" if args.slice_name else args.suite,  # never mistaken for a full run
        {
            "coverage_status": coverage_status(),
            "calibration": cal_state or calibration.status(),
            "open_gates": open_gates(results, targets),
            "gate": failures,
            "slices": results,
        },
    )
    for failure in failures:
        log.error("gate: %s", failure)
    return 1 if args.gate and failures else 0


def _main() -> int:
    try:
        return main()
    finally:
        search.close_readers()  # close the cached Qdrant reader before interpreter shutdown


if __name__ == "__main__":
    raise SystemExit(_main())
