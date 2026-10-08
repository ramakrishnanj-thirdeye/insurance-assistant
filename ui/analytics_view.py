"""Analytics block under an answer (spec 02, spec 10): the validated SQL, the result table and a chart.

Minimal styling; M8 polishes it.
"""

from typing import Any

import altair as alt
import pandas as pd
import streamlit as st


def render_analytics(analytics: dict[str, Any], key: str) -> None:
    frame = pd.DataFrame(analytics.get("rows", []), columns=analytics.get("columns", []))
    chart = analytics.get("chart")
    if chart and not frame.empty:
        st.altair_chart(_chart(frame, chart), width="stretch", key=f"{key}-chart")
    caption = f"{analytics.get('row_count', len(frame))} rows"
    if analytics.get("truncated"):
        caption += " (stopped at the row limit)"
    st.dataframe(frame, hide_index=True, width="stretch", key=f"{key}-table")
    st.caption(caption)
    with st.expander("SQL"):
        st.code(analytics.get("sql", ""), language="sql")


def _chart(frame: pd.DataFrame, spec: dict[str, Any]) -> alt.Chart:
    x, y = spec["x"], spec["y"]
    if spec["type"] == "line":
        data = frame.assign(**{x: pd.to_datetime(frame[x])})
        return (
            alt.Chart(data)
            .mark_line(point=True)
            .encode(x=alt.X(f"{x}:T", title=x), y=alt.Y(f"{y}:Q", title=y))
        )
    return (
        alt.Chart(frame)
        .mark_bar()
        .encode(
            x=alt.X(f"{x}:N", sort="-y", title=x), y=alt.Y(f"{y}:Q", title=y), tooltip=list(frame.columns)
        )
    )
