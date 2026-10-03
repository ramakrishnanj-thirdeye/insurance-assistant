"""Eval runner (spec 11). Retrieval-only for now: `--suite ablation`, or `--slice policy_clauses`.

The full runner (routing, judged slices, the eval-fast gate) arrives with spec 11 in M7.
"""

import argparse

from insurai.eval.retrieval import CONFIGS, SLICE, load_policy_slice, run_ablation, run_config, write_report
from insurai.observability import get_logger

log = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="insurai.eval.run")
    parser.add_argument("--suite", choices=["fast", "full", "ablation"], required=True)
    parser.add_argument("--slice", dest="slice_name")
    args = parser.parse_args(argv)

    items = load_policy_slice()
    if args.suite == "ablation":
        run_ablation(items)
        return 0
    if args.slice_name == SLICE:
        result = run_config(items, CONFIGS["E"])
        log.info("policy_clauses (config E): %s", result["metrics"])
        write_report(args.suite, {"slices": {SLICE: result}})
        return 0
    log.error(
        "suite %r is not built yet (spec 11, M7); use --suite ablation or --slice %s", args.suite, SLICE
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
