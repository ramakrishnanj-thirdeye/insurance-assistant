"""Baseline and gate (spec 11 Gate).

`python -m insurai.eval.baseline --promote-latest` (make eval-baseline) copies the newest full report (JSON
and markdown) to eval/reports/baseline.json and baseline.md; draft items stay flagged in both.

`gate(results, baseline, targets)` checks every target metric that ran:
- with no baseline value, the metric fails when it misses its target (the pre-baseline behaviour);
- with one, it fails when it regresses from the baseline by more than the tolerance, or misses a target the
  baseline had met.
The tolerance is 2 points (0.02), widened to one item (1/n) for a proportion with n < 30: on a 15-item
slice one item is 6.7 points, so a single flip is tolerated as noise but two are not. A target is a minimum
(a number) or `{max: x}` (false_refusal), where a rise is the regression.

Advisory targets (`advisory_keys`): while the judge is uncalibrated, the judge-based metrics named in
`eval.advisory_when_uncalibrated` are reported but neither gate nor count as open gates.
"""

import argparse
import json
import shutil
from collections.abc import Collection
from pathlib import Path
from typing import Any

from insurai.eval.stats import SMALL_N
from insurai.observability import get_logger
from insurai.settings import get_settings

log = get_logger(__name__)

DROP = 0.02
EPS = 1e-9
ROUNDING = 1e-4  # reported ratios have 4 decimals: a difference of two may be off by this much
BASELINE = "baseline"
Target = float | dict[str, float]


def target_bound(target: Target) -> tuple[str, float]:
    """("min", x) for a number, ("max", x) for {max: x}."""
    if isinstance(target, dict):
        return ("max", float(target["max"])) if "max" in target else ("min", float(target["min"]))
    return "min", float(target)


def meets(value: float, target: Target) -> bool:
    kind, bound = target_bound(target)
    return value <= bound + EPS if kind == "max" else value >= bound - EPS


def tolerance(n: int | None) -> float:
    """2 points, or one item when the proportion has fewer than 30 items."""
    return max(DROP, 1 / n) if n and n < SMALL_N else DROP


def metric_of(results: dict[str, Any], key: str) -> tuple[float | None, int | None]:
    """(value, n) of `slice.metric`; None when the slice did not run or the metric is not a number."""
    slice_name, metric = key.split(".", 1)
    result = results.get(slice_name)
    if not result:
        return None, None
    value = result.get("metrics", {}).get(metric)
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None, None
    counts = result.get("counts", {}).get(metric)
    return float(value), (int(counts[1]) if counts else None)


def advisory_keys(targets: dict[str, Target], metrics: Collection[str], calibrated: bool) -> set[str]:
    """Target keys (`slice.metric`) that are advisory: the named metrics, in any slice, while uncalibrated."""
    if calibrated:
        return set()
    return {key for key in targets if key.split(".", 1)[1] in set(metrics)}


def gate(
    results: dict[str, Any],
    baseline: dict[str, Any] | None,
    targets: dict[str, Target],
    advisory: Collection[str] = (),
) -> list[str]:
    """Failures (one line each) for target metrics in `results` against `baseline` slices; advisory keys are
    skipped."""
    failures = []
    for key, target in targets.items():
        value, n = metric_of(results, key)
        if value is None or key in advisory:
            continue
        kind, bound = target_bound(target)
        base, _ = metric_of(baseline or {}, key)
        if base is None:
            if not meets(value, target):
                failures.append(f"{key} = {value} misses target {kind} {bound} (no baseline value)")
            continue
        regression = value - base if kind == "max" else base - value
        tol = tolerance(n)
        if regression > tol + ROUNDING:
            failures.append(f"{key} = {value} regressed {regression:.4f} from baseline {base} (> {tol:.4f})")
        elif meets(base, target) and not meets(value, target):
            failures.append(f"{key} = {value} misses target {kind} {bound}, which the baseline met ({base})")
    return failures


def open_gates(
    results: dict[str, Any], targets: dict[str, Target], advisory: Collection[str] = ()
) -> list[dict[str, Any]]:
    """Every target the run does not meet, whether or not the baseline met it (the report's Open gates); an
    advisory target is listed with `advisory: true` and is not an open gate."""
    out = []
    for key, target in targets.items():
        value, _ = metric_of(results, key)
        if value is None or meets(value, target):
            continue
        slice_name, metric = key.split(".", 1)
        kind, bound = target_bound(target)
        counts = results[slice_name].get("counts", {}).get(metric)
        entry = {"metric": key, "value": value, "target": f"{kind} {bound}", "counts": counts}
        out.append(entry | ({"advisory": True} if key in advisory else {}))
    return out


def load_baseline(reports: Path | None = None) -> dict[str, Any] | None:
    path = (reports or get_settings().paths.eval_reports) / f"{BASELINE}.json"
    if not path.exists():
        return None
    return dict(json.loads(path.read_text(encoding="utf-8")).get("slices", {}))


def promote_latest(reports: Path | None = None) -> Path:
    """Copy the newest full_<ts>.json (and its .md) to baseline.json and baseline.md."""
    reports = reports or get_settings().paths.eval_reports
    runs = sorted(reports.glob("full_*.json"))
    if not runs:
        raise FileNotFoundError(f"no full_*.json in {reports}: run `make eval` first")
    latest = runs[-1]
    report = json.loads(latest.read_text(encoding="utf-8"))
    report["baseline_of"] = latest.name
    target = reports / f"{BASELINE}.json"
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md = latest.with_suffix(".md")
    if md.exists():
        shutil.copyfile(md, reports / f"{BASELINE}.md")
    drafts = sum(
        int(s.get("metrics", {}).get("draft_items", 0) or 0) for s in report.get("slices", {}).values()
    )
    log.info("promoted %s to %s (%d draft items flagged)", latest.name, target.name, drafts)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="insurai.eval.baseline")
    parser.add_argument("--promote-latest", action="store_true", required=True)
    parser.parse_args(argv)
    promote_latest()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
