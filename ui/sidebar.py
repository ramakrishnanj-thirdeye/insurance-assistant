"""Sidebar on every page (spec 10): persona and principal, status badges, Conversations list."""

from collections.abc import Callable

import state
import streamlit as st
from views import thread_label

from insurai.api.client import ApiProblem, Identity
from insurai.settings import get_settings


def _identity_picker() -> Identity:
    customers = [c.customer_id for c in get_settings().ui.sample_customers]
    hints = {c.customer_id: c.hint for c in get_settings().ui.sample_customers}
    if "persona" not in st.session_state:  # first run: restore the identity from the URL
        persona = st.query_params.get("persona", state.PERSONAS[0])
        st.session_state["persona"] = persona if persona in state.PERSONAS else state.PERSONAS[0]
        principal = st.query_params.get("principal", customers[0] if customers else "")
        st.session_state["principal"] = principal if principal in customers else (customers or [""])[0]
    persona = st.selectbox("Persona", state.PERSONAS, key="persona")
    principal = None
    if persona == "customer":
        principal = st.selectbox(
            "Customer",
            customers,
            key="principal",
            format_func=lambda c: f"{c} · {hints[c]}" if hints.get(c) else c,
        )
    ident = Identity(persona=persona, principal_id=principal)
    st.query_params["persona"] = persona
    if principal:
        st.query_params["principal"] = principal
    else:
        st.query_params.pop("principal", None)
    previous = st.session_state.get("identity")
    if previous is not None and previous != ident:
        state.reset_conversation()  # a new identity starts a new conversation
    st.session_state["identity"] = ident
    return ident


def _badges() -> None:
    health = st.session_state.get("health")
    if health is None:
        try:
            health = st.session_state["health"] = state.api().health()
        except ApiProblem as exc:
            st.error(exc.detail)
            return
    st.caption(
        f"LLM `{health['llm_profile']}` · as of `{health['as_of']}` · coverage `{health['coverage_status']}`"
        + ("" if health.get("status") == "ok" else " · ⚠ degraded")
    )


def _conversations(ident: Identity) -> None:
    st.subheader("Conversations")
    st.button("New conversation", on_click=state.reset_conversation, width="stretch", key="new-conversation")
    try:
        threads = state.api().list_threads(ident)
    except ApiProblem as exc:
        st.caption(f"Could not load conversations: {exc.detail}")
        return
    if not threads:
        st.caption("No conversations yet.")
    open_id = st.session_state.get("thread_id") or st.query_params.get("thread")
    for t in threads:
        tid = t["thread_id"]
        left, right = st.columns([5, 1], vertical_alignment="center")
        left.button(
            thread_label(t),
            key=f"open-{tid}",
            on_click=state.open_thread,
            args=(tid,),
            type="primary" if tid == open_id else "secondary",
            width="stretch",
        )
        with right.popover("⋯", key=f"menu-{tid}"):
            title = st.text_input("Title", value=t["title"], key=f"title-{tid}")
            if st.button("Rename", key=f"rename-{tid}"):
                _act(lambda tid=tid, title=title: state.api().rename_thread(tid, title, ident))
            if st.button("Delete", key=f"delete-{tid}", type="primary"):
                _act(lambda tid=tid: state.api().delete_thread(tid, ident), clears=tid == open_id)


def _act(call: Callable[[], object], clears: bool = False) -> None:
    try:
        call()
        if clears:
            state.reset_conversation()
    except ApiProblem as exc:
        state.flash(exc.detail)
    st.rerun()


def render() -> Identity:
    with st.sidebar:
        st.title("Insurance assistant")
        ident = _identity_picker()
        _badges()
        _conversations(ident)
    return ident
