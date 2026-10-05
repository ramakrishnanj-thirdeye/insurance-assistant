"""Eval runner (spec 11). Slices so far: policy_clauses (retrieval), sql_facts (tools), routing (planner,
spec 06), e2e_sql_facts (full graph, reported only) and claim_analysis (rules engine and dossier, spec 07).

`--suite fast` runs every slice built so far; `--gate` fails when a metric is below its target in settings
`eval.targets`. `--sample N` runs a seeded N-item subset of the routing slice (development smoke).
Judged items and the baseline comparison arrive with spec 11 (M7).
"""

import argparse
from collections.abc import Callable
from typing import Any

from insurai.eval import claim_analysis, e2e_sql_facts, routing, sql_facts
from insurai.eval.retrieval import CONFIGS, SLICE, load_policy_slice, run_ablation, run_config, write_report
from insurai.observability import get_logger
from insurai.retrieval import search
from insurai.settings import get_settings

log = get_logger(__name__)

SLICES: dict[str, Callable[..., dict[str, Any]]] = {
    SLICE: lambda: run_config(load_policy_slice(), CONFIGS["E"]),
    sql_facts.SLICE: sql_facts.run_slice,
    routing.SLICE: routing.run_slice,
    e2e_sql_facts.SLICE: e2e_sql_facts.run_slice,
    claim_analysis.SLICE: claim_analysis.run_slice,
}


def gate(results: dict[str, dict[str, Any]], targets: dict[str, float]) -> list[str]:
    """Failures for `slice.metric` targets whose slice ran and scored below target."""
    failures = []
    for key, target in targets.items():
        slice_name, metric = key.split(".", 1)
        if slice_name not in results:
            continue
        value = results[slice_name]["metrics"][metric]
        if value < target:
            failures.append(f"{key} = {value} < target {target}")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="insurai.eval.run")
    parser.add_argument("--suite", choices=["fast", "full", "ablation"], required=True)
    parser.add_argument("--slice", dest="slice_name", choices=sorted(SLICES))
    parser.add_argument("--gate", action="store_true", help="exit 1 when a metric misses its target")
    parser.add_argument("--sample", type=int, help="routing only: score a seeded subset of N items")
    args = parser.parse_args(argv)

    if args.suite == "ablation":
        run_ablation(load_policy_slice())
        return 0
    if args.slice_name:
        names = [args.slice_name]
    elif args.suite == "fast":
        names = list(SLICES)
    else:
        log.error("suite %r is not built yet (spec 11, M7); use --suite fast or --slice", args.suite)
        return 2

    results = {
        name: SLICES[name](sample=args.sample) if name == routing.SLICE else SLICES[name]() for name in names
    }
    for name, result in results.items():
        log.info("%s: %s", name, result["metrics"])
    write_report(args.suite, {"slices": results})
    if not args.gate:
        return 0
    failures = gate(results, get_settings().eval.targets)
    for failure in failures:
        log.error("gate: %s", failure)
    return 1 if failures else 0


def _main() -> int:
    try:
        return main()
    finally:
        search.close_readers()  # close the cached Qdrant reader before interpreter shutdown


if __name__ == "__main__":
    raise SystemExit(_main())
