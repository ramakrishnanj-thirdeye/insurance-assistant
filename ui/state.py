"""Session state and URL state for the UI (spec 10: session_state only, no browser storage).

The URL carries persona, principal and the open thread (`st.query_params`), so a browser refresh reopens
the same conversation under the same identity.
"""

from typing import Any

import streamlit as st
from status import select_tone

from insurai.api.client import ApiClient, Identity

PERSONAS = ("claims_agent", "supervisor", "customer")


def api() -> ApiClient:
    if "api" not in st.session_state:  # tests put a fake client here before the first run
        st.session_state["api"] = ApiClient.from_settings()
    return st.session_state["api"]


def identity() -> Identity:
    return st.session_state["identity"]


def tone() -> str:
    """The status-line tone: the sidebar choice, always professional for the customer persona."""
    return select_tone(identity().persona, st.session_state.get("tone"))


def reset_conversation() -> None:
    """Forget the open thread (New conversation, or a persona/principal switch)."""
    st.session_state["thread_id"] = None
    st.session_state["messages"] = []
    st.session_state["pending_review"] = None
    st.query_params.pop("thread", None)


def open_thread(thread_id: str) -> None:
    """Point the URL at a thread; the Chat page loads it on this run."""
    reset_conversation()
    st.query_params["thread"] = thread_id


def set_thread(thread_id: str) -> None:
    st.session_state["thread_id"] = thread_id
    st.query_params["thread"] = thread_id


def flash(message: str, kind: str = "error") -> None:
    """A message shown once on the next run (the page reruns after each turn)."""
    st.session_state["flash"] = (kind, message)


def pop_flash() -> tuple[str, str] | None:
    return st.session_state.pop("flash", None)


def init() -> None:
    for key, default in (("thread_id", None), ("messages", []), ("pending_review", None)):
        st.session_state.setdefault(key, default)


def messages() -> list[dict[str, Any]]:
    return st.session_state["messages"]
