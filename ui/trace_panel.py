"""Minimal Trace expander for an assistant message (spec 10). The full AC-10-02 layout is M8."""

from typing import Any

import streamlit as st
from views import compact, duration_ms

HEADLINE_KINDS = ("intent", "entity")


def render_trace(trace: list[dict[str, Any]], key: str) -> None:
    if not trace:
        return
    with st.expander("Trace", expanded=False):
        for ev in trace:
            if ev.get("kind") in HEADLINE_KINDS:
                st.markdown(f"**{ev['kind']}** `{ev.get('name', '')}` {compact(ev.get('data', {}))}")
        rows = [
            {
                "kind": ev.get("kind"),
                "name": ev.get("name"),
                "ms": duration_ms(ev),
                "details": compact(ev.get("data", {})),
            }
            for ev in trace
            if ev.get("kind") not in HEADLINE_KINDS
        ]
        if rows:
            st.dataframe(rows, hide_index=True, width="stretch", key=f"{key}-events")
        for i, ev in enumerate(trace):
            data = ev.get("data", {})
            if isinstance(data.get("sql"), str):
                st.caption(f"SQL · {ev.get('name')}")
                st.code(data["sql"], language="sql")
            for field, value in data.items():
                if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
                    st.caption(f"{ev.get('kind')} · {ev.get('name')} · {field}")
                    st.dataframe(value, hide_index=True, width="stretch", key=f"{key}-{i}-{field}")
