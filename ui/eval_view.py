"""Pure helpers for the Eval Dashboard (spec 10, AC-10-11): metric rows, failures, ablation, history.

Reports are what /eval/reports returned; the gate logic and interval maths are the eval package's own
(`insurai.eval.baseline`, `insurai.eval.stats`), so the dashboard and the markdown reports agree.
"""

import json
from typing import Any

from insurai.eval.baseline import meets, target_bound
from insurai.eval.stats import fmt_prop, wilson

Target = float | dict[str, float]
FAILURE_LISTS = ("wrong", "misses", "not_handled", "errors")
EXPECTED_FIELDS = ("gold", "expected_route", "gold_rows", "expected_entities", "labels")
ACTUAL_FIELDS = ("answer", "route", "top5", "rows", "narrative", "reason", "error")
ABLATION_METRICS = {"recall_at_5": "recall@5", "product_precision_at_5": "product precision@5"}
TEXT_MAX = 240


def run_label(summary: dict[str, Any]) -> str:
    stamp = (summary.get("created_at") or "")[:16].replace("T", " ")
    sha = summary.get("git_sha") or "?"
    if summary.get("baseline_of"):
        return f"baseline ({summary['baseline_of'].removesuffix('.json')}) · git {sha}"
    return f"{summary.get('suite')} · {stamp} UTC · git {sha}"


def default_run(summaries: list[dict[str, Any]]) -> int:
    """The newest run that is not an ablation (summaries arrive newest first)."""
    return next((i for i, s in enumerate(summaries) if s.get("suite") != "ablation"), 0)


def target_text(target: Target) -> str:
    kind, bound = target_bound(target)
    return f"{'≥' if kind == 'min' else '≤'} {bound:g}"


def _short(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= TEXT_MAX else text[: TEXT_MAX - 1] + "…"


def metric_rows(report: dict[str, Any], targets: dict[str, Target]) -> list[dict[str, Any]]:
    """One row per target: value, "k of n", 95% interval, target, and met / open / advisory / not run."""
    slices = report.get("slices") or {}
    advisory = set(report.get("advisory") or [])
    rows = []
    for key, target in targets.items():
        slice_name, metric = key.split(".", 1)
        body = slices.get(slice_name) or {}
        value = (body.get("metrics") or {}).get(metric)
        counts = (body.get("counts") or {}).get(metric)
        if not isinstance(value, int | float) or isinstance(value, bool):
            rows.append(
                {
                    "metric": key,
                    "value": None,
                    "k of n": "",
                    "95% interval": "",
                    "target": target_text(target),
                    "status": "not run",
                }
            )
            continue
        k_of_n = interval = ""
        if counts:
            k, n = int(counts[0]), int(counts[1])
            lo, hi = wilson(k, n)
            k_of_n, interval = f"{k} of {n}", f"{lo:.2f}–{hi:.2f}"
        if key in advisory:
            status = "advisory (judge uncalibrated)"
        else:
            status = "✓ met" if meets(float(value), target) else "✗ open"
        rows.append(
            {
                "metric": key,
                "value": round(float(value), 4),
                "k of n": k_of_n,
                "95% interval": interval,
                "target": target_text(target),
                "status": status,
            }
        )
    return rows


def gate_rows(report: dict[str, Any], advisory: bool) -> list[dict[str, Any]]:
    """Open gates (target missed and gated) or the advisory ones, as the report recorded them."""
    rows = []
    for g in report.get("open_gates") or []:
        if bool(g.get("advisory")) is not advisory:
            continue
        counts = g.get("counts")
        shown = fmt_prop(int(counts[0]), int(counts[1])) if counts else f"{g.get('value')}"
        rows.append({"metric": g.get("metric"), "value": shown, "target": g.get("target")})
    return rows


def calibration_rows(report: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Part A (correctness judge vs human) and Part B (V7 verdicts vs human) rows."""
    cal = report.get("calibration") or {}
    a = [
        {
            "id": r.get("id"),
            "item": r.get("item"),
            "human": r.get("human"),
            "judge": r.get("judge"),
            "agree": "yes" if r.get("agree") else "no",
        }
        for r in (cal.get("part_a") or {}).get("rows", [])
    ]
    b = [
        {
            "id": r.get("id"),
            "item": r.get("item"),
            "claim": _short(r.get("claim", "")),
            "judge": r.get("verdict"),
            "human": r.get("human"),
            "still reaches the judge": "yes" if r.get("reaches_judge", True) else "no",
        }
        for r in (cal.get("part_b") or {}).get("rows", [])
    ]
    return a, b


def failed_items(report: dict[str, Any], questions: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Items a slice listed as wrong, missed, not handled or errored, with what was expected and produced."""
    questions = questions if questions is not None else report.get("questions") or {}
    rows = []
    for slice_name, body in (report.get("slices") or {}).items():
        if not isinstance(body, dict):
            continue
        metrics = body.get("metrics") or {}
        failed: list[str] = []
        for field in FAILURE_LISTS:
            values = metrics.get(field)
            if isinstance(values, list):
                failed += [str(v if not isinstance(v, dict) else v.get("id")) for v in values]
        items = {str(i.get("id")): i for i in body.get("items", []) if isinstance(i, dict)}
        for item_id in dict.fromkeys(failed):
            item = items.get(item_id, {})
            expected = next((item[f] for f in EXPECTED_FIELDS if item.get(f) not in (None, "", [])), "")
            actual = next((item[f] for f in ACTUAL_FIELDS if item.get(f) not in (None, "", [])), "")
            rows.append(
                {
                    "slice": slice_name,
                    "id": item_id,
                    "question": _short(questions.get(item_id, "")),
                    "expected": _short(expected),
                    "actual": _short(actual),
                    "judge reason": _short(item.get("judge_reason") or ""),
                }
            )
    return rows


def ablation_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Long-form rows (config, metric, value) for grouped bars of recall@5 and product precision@5."""
    rows = []
    for name, body in sorted((report.get("configs") or {}).items()):
        metrics = body.get("metrics") or {}
        for key, label in ABLATION_METRICS.items():
            if isinstance(metrics.get(key), int | float):
                rows.append(
                    {
                        "config": f"{name} {body.get('description', '')}".strip(),
                        "metric": label,
                        "value": float(metrics[key]),
                    }
                )
    return rows


def history_rows(summaries: list[dict[str, Any]], metrics: list[str]) -> list[dict[str, Any]]:
    """One row per run and metric, oldest first; the baseline copy and ablation runs are left out."""
    rows = []
    for s in sorted(summaries, key=lambda s: s.get("created_at") or ""):
        if s.get("baseline_of") or s.get("suite") == "ablation":
            continue
        for key in metrics:
            slice_name, metric = key.split(".", 1)
            value = (s.get("headline") or {}).get(slice_name, {}).get(metric)
            if isinstance(value, int | float):
                rows.append(
                    {
                        "run": s.get("run_id"),
                        "created_at": s.get("created_at"),
                        "metric": key,
                        "value": float(value),
                    }
                )
    return rows
