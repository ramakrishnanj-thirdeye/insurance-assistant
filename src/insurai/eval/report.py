"""Markdown summary next to each eval report JSON (spec 11 Runner output).

Header (suite, time, git SHA, profile, coverage status, draft items, judge calibration), Open gates (every
target the run misses, whether or not the baseline met it), the gate result, then one table per slice.
Every proportion shows counts and a 95% Wilson interval ("10 of 15, 0.42–0.85" below 30 items).
"""

import json
from pathlib import Path
from typing import Any

from insurai.eval.calibration import describe
from insurai.eval.stats import SMALL_N, fmt_prop

LIST_PREVIEW = 12


def render(report: dict[str, Any]) -> str:
    slices: dict[str, Any] = report.get("slices", {})
    drafts = sum(int(s.get("metrics", {}).get("draft_items", 0) or 0) for s in slices.values())
    lines = [
        f"# Eval report: {report.get('suite')} ({report.get('created_at')})",
        "",
        f"- git {report.get('git_sha')} · profile {report.get('profile')} · coverage matrix "
        f"{report.get('coverage_status')}",
    ]
    if report.get("baseline_of"):
        lines.append(f"- baseline promoted from {report['baseline_of']}")
    if drafts:
        lines.append(f"- **{drafts} draft items** (not yet signed off) are included in the metrics below")
    lines += [f"- {line}" for line in describe(report.get("calibration") or {})]
    lines += ["", "## Open gates", ""]
    open_gates = report.get("open_gates") or []
    if open_gates:
        lines += ["| Metric | Value | Target |", "| --- | --- | --- |"]
        for g in open_gates:
            value = fmt_prop(*g["counts"]) if g.get("counts") else str(g["value"])
            lines.append(f"| {g['metric']} | {value} | {g['target']} |")
    else:
        lines.append("Every target that ran is met.")
    gate = report.get("gate")
    if gate is not None:
        lines += ["", "## Gate", ""]
        lines += [f"- FAIL {f}" for f in gate] if gate else ["Pass."]
        lines += [
            "",
            "Tolerance: a regression from the baseline fails above 2 points, or above one item (1/n) for a "
            f"proportion with n < {SMALL_N}; a target the baseline met must still be met.",
        ]
    for name, result in slices.items():
        lines += ["", f"## {name}", "", "| Metric | Value |", "| --- | --- |"]
        counts = result.get("counts", {})
        for metric, value in result.get("metrics", {}).items():
            lines.append(f"| {metric} | {_cell(value, counts.get(metric))} |")
    return "\n".join(lines) + "\n"


def write_markdown(report: dict[str, Any], json_path: Path) -> Path:
    path = json_path.with_suffix(".md")
    path.write_text(render(report), encoding="utf-8")
    return path


def _cell(value: Any, counts: list[int] | None) -> str:
    if counts:
        return fmt_prop(int(counts[0]), int(counts[1]))
    if isinstance(value, list):
        shown = ", ".join(str(v) for v in value[:LIST_PREVIEW])
        more = f" … (+{len(value) - LIST_PREVIEW})" if len(value) > LIST_PREVIEW else ""
        return f"{len(value)}: {shown}{more}" if value else "none"
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False).replace("|", "\\|")
    return str(value)
