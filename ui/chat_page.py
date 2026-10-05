"""Chat page (spec 10): streamed answers with node progress, Trace expander, review card on interrupt."""

import time
from collections.abc import Iterator
from typing import Any

import state
import streamlit as st
from trace_panel import render_trace
from views import WAIT_CAPTION, progress_line

from insurai.api.client import ApiProblem, Event, TurnView
from insurai.tools.access import load_personas

RESUME_ACTIONS = {"approve": "Approve", "override": "Override", "request_info": "Request info"}


def _load_thread_from_url() -> None:
    """Reopen the thread named in the URL (sidebar click, or a browser refresh)."""
    wanted = st.query_params.get("thread")
    if not wanted or wanted == st.session_state["thread_id"]:
        return
    try:
        detail = state.api().get_thread(wanted, state.identity())
    except ApiProblem as exc:
        state.reset_conversation()
        st.info(f"Could not open that conversation: {exc.detail}")
        return
    msgs: list[dict[str, Any]] = [{"role": m["role"], "content": m["content"]} for m in detail["messages"]]
    for m in reversed(msgs):
        if m["role"] == "assistant":
            m["trace"] = detail.get("last_trace", [])
            break
    st.session_state["thread_id"] = detail["thread_id"]
    st.session_state["messages"] = msgs
    st.session_state["pending_review"] = detail.get("pending_review")


def _history() -> None:
    for i, m in enumerate(state.messages()):
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            if m.get("progress"):
                with st.expander(f"Steps · {m['elapsed_s']:.1f} s"):
                    st.markdown("  \n".join(m["progress"]))
            if m["role"] == "assistant":
                render_trace(m.get("trace", []), key=f"trace-{i}")


def _stream(events: Iterator[Event], label: str) -> tuple[TurnView, float]:
    """Show node and tool events while the answer is prepared; fold them into a TurnView."""
    view = TurnView()
    wait = st.caption(WAIT_CAPTION)
    started = time.perf_counter()
    with st.status(label, expanded=True) as status:
        try:
            for event, data in events:
                view.apply(event, data)
                if event in ("node", "tool"):
                    st.write(progress_line(event, data))
                elif event == "thread" and view.thread_id:
                    state.set_thread(view.thread_id)
        except ApiProblem as exc:
            view.error = exc.detail
            if exc.code == "REVIEW_PENDING" and isinstance(exc.extra.get("review"), dict):
                view.interrupt = exc.extra["review"]
        secs = time.perf_counter() - started
        if view.error:
            status.update(label="Failed", state="error", expanded=False)
        elif view.interrupt is not None:
            status.update(label=f"Paused for review after {secs:.1f} s", state="complete", expanded=False)
        else:
            status.update(label=f"Answered in {secs:.1f} s", state="complete", expanded=False)
    wait.empty()
    return view, secs


def _apply(view: TurnView, elapsed_s: float) -> None:
    """Keep what the turn produced, with its progress lines; rerun so the sidebar and history refresh."""
    if view.answer is not None:
        state.messages().append(
            {
                "role": "assistant",
                "content": view.answer,
                "trace": view.trace,
                "citations": view.citations,
                "progress": [progress_line(e, d) for e, d in view.progress],
                "elapsed_s": elapsed_s,
            }
        )
        st.session_state["pending_review"] = None
    if view.interrupt is not None:
        st.session_state["pending_review"] = view.interrupt
    if view.error:
        state.flash(view.error)
    st.rerun()


def _review_card(review: dict[str, Any]) -> None:
    persona = state.identity().persona
    with st.container(border=True):
        st.markdown(
            f"**Review needed · {review.get('claim_id', '')}** (status {review.get('claim_status', '?')})"
        )
        for title, field in (
            ("Escalation reasons", "escalation_reasons"),
            ("Missing documents", "missing_documents"),
            ("Pending documents", "pending_documents"),
        ):
            if items := review.get(field):
                st.markdown(f"*{title}*")
                st.markdown("\n".join(f"- {item}" for item in items))
        if not load_personas()[persona].can_resume_review:
            st.caption("A claims agent or supervisor will review this claim.")
            return
        note = st.text_area("Note", key="review-note", placeholder="Required for Override")
        cols = st.columns(len(RESUME_ACTIONS))
        chosen = None
        for col, (action, label) in zip(cols, RESUME_ACTIONS.items(), strict=True):
            if col.button(label, key=f"review-{action}", width="stretch"):
                chosen = action
    if chosen is None:
        return
    if chosen == "override" and not note.strip():
        st.warning("Add a note explaining the override.")
        return
    events = state.api().resume(st.session_state["thread_id"], chosen, note.strip(), state.identity())
    _apply(*_stream(events, f"Resuming with {RESUME_ACTIONS[chosen]}…"))


def render() -> None:
    state.init()
    _load_thread_from_url()
    if (flash := state.pop_flash()) is not None:
        kind, message = flash
        (st.error if kind == "error" else st.info)(message)
    _history()
    review = st.session_state.get("pending_review")
    if review is not None:
        _review_card(review)
    prompt = st.chat_input(
        "Ask about a claim, a policy or coverage", disabled=review is not None, key="chat-input"
    )
    if review is not None:
        st.caption("Finish the review above before sending a new message.")
    if not prompt:
        return
    state.messages().append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    events = state.api().chat(prompt, st.session_state["thread_id"], state.identity())
    with st.chat_message("assistant"):
        view, elapsed_s = _stream(events, "Preparing answer…")
    if view.thread_id is None:  # rejected before the stream opened: the message never reached the thread
        state.messages().pop()
    _apply(view, elapsed_s)
