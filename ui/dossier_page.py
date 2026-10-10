"""Claim Dossier page (spec 10, AC-10-10): staff personas only; data from /claims/{id}/dossier.

The first load uses narrate=false (fast, deterministic). "Add narrative" asks again with narrate=true for the
narrative, the cited clauses and the customer message draft.
"""

from typing import Any

import state
import streamlit as st
from dossier_view import (
    clause_label,
    document_rows,
    header_fields,
    payable_gap,
    rule_rows,
    shows_consistency,
    timeline_rows,
)

from insurai.api.client import ApiProblem


def _load(claim_id: str, narrate: bool) -> None:
    try:
        with st.spinner("Writing the narrative…" if narrate else f"Loading {claim_id}…"):
            dossier = state.api().dossier(claim_id, state.identity(), narrate=narrate)
    except ApiProblem as exc:
        st.session_state["dossier"] = None
        st.session_state["dossier_error"] = exc.detail
        return
    st.session_state["dossier"] = dossier
    st.session_state["dossier_error"] = None
    st.query_params["claim"] = claim_id


def _header(d: dict[str, Any]) -> None:
    facts = d.get("facts", {})
    st.subheader(f"Claim {d['claim_id']}")
    fields = header_fields(facts)
    for row in (fields[:4], fields[4:]):
        for col, (label, value) in zip(st.columns(len(row)), row, strict=True):
            col.metric(label, value)
    if note := payable_gap(facts):
        st.warning(note)
    if d.get("needs_human_review"):
        st.info("This claim needs human review.")


def _rules(d: dict[str, Any]) -> None:
    st.markdown("#### Rule checklist")
    for row in rule_rows(d.get("rules", [])):
        line = f"{row['badge']} **{row['rule']}**"
        if row["message"]:
            line += f"  \n{row['message']}"
        if row["citation"]:
            line += f" `{row['citation']}`"
        st.markdown(line)


def _documents(d: dict[str, Any]) -> None:
    checklist = d.get("checklist") or {}
    st.markdown("#### Documents")
    if rows := document_rows(checklist):
        st.dataframe(rows, hide_index=True, width="stretch", key="dossier-docs")
    for title, field in (
        ("Missing", "missing"),
        ("Pending verification", "pending"),
        ("Rejected", "rejected"),
    ):
        if items := checklist.get(field):
            st.markdown(f"**{title}:** " + ", ".join(items))
    untracked = checklist.get("untracked") or []
    st.markdown("**Untracked documents:** " + (", ".join(untracked) if untracked else "none"))


def _timeline(d: dict[str, Any]) -> None:
    st.markdown("#### Interactions")
    rows = timeline_rows(d.get("interactions"))
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch", key="dossier-interactions")
    else:
        st.caption("No interactions recorded for this claim.")


def _actions(d: dict[str, Any]) -> None:
    st.markdown("#### Next best actions")
    actions = d.get("next_best_actions") or []
    st.markdown("\n".join(f"1. {a}" for a in actions) if actions else "No action needed.")
    reasons = d.get("escalation_reasons") or []
    if reasons:
        st.markdown("**Escalation reasons:** " + "; ".join(reasons))


def _consistency(d: dict[str, Any]) -> None:
    if not shows_consistency(state.identity().persona):
        return
    st.markdown("#### Consistency flags")
    flags = d.get("consistency") or []
    st.markdown("\n".join(f"- **{f['id']}** {f['name']}" for f in flags) if flags else "None raised.")


def _narrative(d: dict[str, Any]) -> None:
    st.markdown("#### Narrative")
    if d.get("narrative") is None:
        if st.button("Add narrative", key="dossier-narrate"):
            _load(d["claim_id"], narrate=True)
            st.rerun()
        st.caption(
            "Writes a summary, fetches the cited clauses and drafts a customer message (uses the model)."
        )
        return
    st.markdown(d["narrative"])
    if clauses := d.get("clauses"):
        st.markdown("#### Cited clauses")
        for i, clause in enumerate(clauses):
            with st.expander(clause_label(clause), expanded=False):
                st.markdown((clause.get("chunk") or {}).get("text", ""))
                st.caption(f"clause {i + 1} · via {clause.get('via')}")
    if draft := d.get("customer_message_draft"):
        st.markdown("#### Customer message draft")
        st.code(draft, language=None, wrap_lines=True)


def render() -> None:
    st.title("Claim Dossier")
    st.session_state.setdefault("dossier", None)
    st.session_state.setdefault("dossier_error", None)
    with st.form("dossier-form", border=False):
        left, right = st.columns([4, 1], vertical_alignment="bottom")
        claim_id = left.text_input(
            "Claim ID", value=st.query_params.get("claim", ""), placeholder="CLM300210"
        )
        submitted = right.form_submit_button("Load", width="stretch")
    if submitted and claim_id.strip():
        _load(claim_id.strip().upper(), narrate=False)
    elif (
        claim_id.strip() and st.session_state.get("dossier") is None and not st.session_state["dossier_error"]
    ):
        _load(claim_id.strip().upper(), narrate=False)  # a link or refresh with ?claim=…
    if error := st.session_state.get("dossier_error"):
        st.error(error)
    d = st.session_state.get("dossier")
    if not d:
        return
    _header(d)
    _rules(d)
    _documents(d)
    _timeline(d)
    _actions(d)
    _consistency(d)
    _narrative(d)
