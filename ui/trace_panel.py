"""Trace expander for an assistant message (spec 10, AC-10-02, AC-10-12).

The client view comes first: who answered, plain steps with timings, the named verifier checks, then the
evidence (clauses, rules, SQL, model calls). The raw events sit in a separate "Engineer details" expander.
"""

from typing import Any

import streamlit as st
from trace_view import (
    answered_by_label,
    check_rows,
    chunk_rows,
    llm_rows,
    rule_rows,
    sql_blocks,
    step_rows,
    verify_attempts,
)
from views import compact, duration_ms


def render_trace(trace: list[dict[str, Any]], key: str) -> None:
    if not trace:
        return
    with st.expander("How this answer was produced", expanded=False):
        if by := answered_by_label(trace):
            st.markdown(f"**Answered by:** {by}")
        if steps := step_rows(trace):
            st.dataframe(steps, hide_index=True, width="stretch", key=f"{key}-steps")
        if checks := check_rows(trace):
            attempts = verify_attempts(trace)
            st.markdown("**Answer checks**" + (f" (after {attempts} attempts)" if attempts > 1 else ""))
            st.dataframe(checks, hide_index=True, width="stretch", key=f"{key}-checks")
        if chunks := chunk_rows(trace):
            st.markdown("**Policy clauses retrieved**")
            st.dataframe(chunks, hide_index=True, width="stretch", key=f"{key}-chunks")
        if rules := rule_rows(trace):
            st.markdown("**Rule results**")
            st.dataframe(rules, hide_index=True, width="stretch", key=f"{key}-rules")
        for name, sql in sql_blocks(trace):
            st.caption(f"SQL · {name}")
            st.code(sql, language="sql")
        if calls := llm_rows(trace):
            st.markdown("**Language model calls**")
            st.dataframe(calls, hide_index=True, width="stretch", key=f"{key}-llm")
    with st.expander("Engineer details", expanded=False):
        _engineer(trace, key)


def _engineer(trace: list[dict[str, Any]], key: str) -> None:
    """Every event as a row, then the raw JSON."""
    rows = [
        {
            "kind": ev.get("kind"),
            "name": ev.get("name"),
            "ms": duration_ms(ev),
            "details": compact(ev.get("data", {})),
        }
        for ev in trace
    ]
    st.dataframe(rows, hide_index=True, width="stretch", key=f"{key}-events")
    st.json(trace, expanded=False)
