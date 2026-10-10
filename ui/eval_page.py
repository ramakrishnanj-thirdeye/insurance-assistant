"""Eval Dashboard (spec 10, AC-10-11): personas with can_read_eval_reports; data from /eval/reports.

Run selector · every gated metric against its target with "k of n" and the 95% interval · open gates and
advisory metrics · judge calibration tables · retrieval ablation (A–E) · metric history · failed items.
"""

from typing import Any

import altair as alt
import pandas as pd
import state
import streamlit as st
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

from insurai.api.client import ApiProblem
from insurai.eval.calibration import describe
from insurai.settings import get_settings

# Categorical slots 1–8 of the dataviz reference palette, assigned in fixed order (never cycled).
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#7a7974"]


def _reports() -> list[dict[str, Any]] | None:
    try:
        return state.api().eval_reports(state.identity())
    except ApiProblem as exc:
        st.error(exc.detail)
        return None


def _report(run_id: str) -> dict[str, Any] | None:
    cache: dict[str, dict[str, Any]] = st.session_state.setdefault("eval_cache", {})
    if run_id not in cache:
        try:
            cache[run_id] = state.api().eval_report(run_id, state.identity())
        except ApiProblem as exc:
            st.error(exc.detail)
            return None
    return cache[run_id]


def _table_or(rows: list[dict[str, Any]], key: str, empty: str) -> None:
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch", key=key)
    else:
        st.caption(empty)


def _metrics(report: dict[str, Any]) -> None:
    st.subheader("Metrics against targets")
    st.dataframe(
        metric_rows(report, get_settings().eval.targets), hide_index=True, width="stretch", key="eval-metrics"
    )
    left, right = st.columns(2)
    with left:
        st.markdown("**Open gates** (target missed; only a regression fails the gate)")
        _table_or(gate_rows(report, advisory=False), "eval-open", "None.")
    with right:
        st.markdown("**Advisory** (judge-based, not gated while the judge is uncalibrated)")
        if "advisory" not in report:
            st.caption("This run predates advisory metrics.")
        elif rows := gate_rows(report, advisory=True):
            st.dataframe(rows, hide_index=True, width="stretch", key="eval-advisory")
        else:
            st.caption("None.")


def _calibration(report: dict[str, Any]) -> None:
    st.subheader("Judge calibration")
    cal = report.get("calibration")
    if not cal:
        st.caption("This run has no calibration section.")
        return
    st.markdown("\n".join(f"- {line}" for line in describe(cal)))
    part_a, part_b = calibration_rows(report)
    left, right = st.columns(2)
    with left:
        st.markdown("**Part A: correctness judge vs human score**")
        _table_or(part_a, "eval-cal-a", "Awaiting human scores.")
    with right:
        st.markdown("**Part B: V7 'unsupported' verdicts vs human**")
        _table_or(part_b, "eval-cal-b", "Awaiting marks.")


def _ablation(summaries: list[dict[str, Any]]) -> None:
    st.subheader("Retrieval ablation")
    latest = next((s for s in summaries if s.get("suite") == "ablation"), None)
    report = _report(latest["run_id"]) if latest else None
    rows = ablation_rows(report) if report else []
    if not rows:
        st.caption("No ablation run yet (`make eval-ablation`).")
        return
    frame = pd.DataFrame(rows)
    chart = (
        alt.Chart(frame)
        .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, size=18)
        .encode(
            x=alt.X("config:N", title=None, axis=alt.Axis(labelAngle=0, labelLimit=160)),
            xOffset=alt.XOffset("metric:N"),
            y=alt.Y("value:Q", title=None, scale=alt.Scale(domain=[0, 1])),
            color=alt.Color(
                "metric:N", scale=alt.Scale(range=SERIES[:2]), legend=alt.Legend(orient="top", title=None)
            ),
            tooltip=["config", "metric", alt.Tooltip("value:Q", format=".4f")],
        )
        .properties(height=280)
    )
    st.altair_chart(chart, width="stretch", key="eval-ablation-chart")
    st.caption(f"{run_label(latest)} · config F (LLM rewrite) deferred: 3-day scope")  # type: ignore[arg-type]


def _history(summaries: list[dict[str, Any]]) -> None:
    st.subheader("Metric history")
    targets = list(get_settings().eval.targets)
    chosen = st.multiselect(
        "Metrics",
        targets,
        default=["policy_clauses.recall_at_5", "routing.intent_accuracy", "analytics.exec_accuracy"],
        key="eval-history-metrics",
        max_selections=len(SERIES),
    )
    rows = history_rows(summaries, chosen)
    if not rows:
        st.caption("No run recorded these metrics.")
        return
    frame = pd.DataFrame(rows).assign(created_at=lambda f: pd.to_datetime(f["created_at"]))
    chart = (
        alt.Chart(frame)
        .mark_line(point=alt.OverlayMarkDef(size=64), strokeWidth=2)
        .encode(
            x=alt.X("created_at:T", title=None),
            y=alt.Y("value:Q", title=None, scale=alt.Scale(zero=False)),
            color=alt.Color(
                "metric:N",
                scale=alt.Scale(domain=chosen, range=SERIES[: len(chosen)]),  # fixed order, never cycled
                legend=alt.Legend(orient="top", title=None, columns=2),
            ),
            tooltip=["run", "metric", alt.Tooltip("value:Q", format=".4f")],
        )
        .properties(height=280)
    )
    st.altair_chart(chart, width="stretch", key="eval-history-chart")


def _failures(report: dict[str, Any]) -> None:
    st.subheader("Failed items")
    rows = failed_items(report)
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch", key="eval-failed")
    else:
        st.caption("No failed items in this run.")


def render() -> None:
    st.title("Eval Dashboard")
    summaries = _reports()
    if summaries is None:
        return
    if not summaries:
        st.info("No eval reports yet. Run `make eval-fast` or `make eval`.")
        return
    runs = [s for s in summaries if s.get("suite") != "ablation"] or summaries
    index = default_run(runs)
    chosen = st.selectbox(
        "Run", range(len(runs)), index=index, format_func=lambda i: run_label(runs[i]), key="eval-run"
    )
    report = _report(runs[chosen]["run_id"])
    if report is None:
        return
    st.caption(
        f"Profile `{report.get('profile', '?')}` · coverage matrix `{report.get('coverage_status', '?')}` · "
        f"gate {'passes' if not report.get('gate') else 'fails: ' + '; '.join(report['gate'])}"
    )
    _metrics(report)
    _calibration(report)
    _ablation(summaries)
    _history(summaries)
    _failures(report)
