"""The Streamlit Chat page driven by AppTest, with a fake API client in session_state (no server)."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest
from trace_fixtures import POLICY_TRACE
from views import REVIEW_BADGE

from insurai.api.client import ApiProblem, Event, Identity

pytestmark = pytest.mark.unit

APP = Path(__file__).resolve().parents[2] / "ui" / "app.py"
NOW = datetime.now(UTC).isoformat()
REVIEW = {
    "claim_id": "CLM300210",
    "claim_status": "Approved",
    "needs_human_review": True,
    "counts": {"findings": 5, "blockers": 2, "needs_review": 1},
    "blockers": ["The claim date falls outside the policy period."],
    "escalation_reasons": ["Fraud risk score at or above the review threshold"],
    "next_best_actions": ["Request Claim Form from the customer"],
    "missing_documents": ["Discharge summary"],
    "pending_documents": [],
}
TRACE = [
    {"kind": "intent", "name": "claim_status", "turn": 1, "start_ms": 0, "end_ms": 0, "data": {}},
    {"kind": "tool", "name": "get_claim", "turn": 1, "start_ms": 0, "end_ms": 35, "data": {"ok": True}},
]
ANALYTICS = {
    "sql": "SELECT policy_type, COUNT(*) AS claims FROM silver.claims GROUP BY 1 LIMIT 200",
    "columns": ["policy_type", "claims"],
    "rows": [["Health", 81403], ["Motor", 28951], ["Travel", 9646]],
    "row_count": 3,
    "truncated": False,
    "chart": {"type": "bar", "x": "policy_type", "y": "claims"},
}
PROGRESS: list[Event] = [
    ("node", {"name": "planner", "status": "start"}),
    ("node", {"name": "planner", "status": "end", "ms": 412.0, "interrupted": False}),
    ("tool", {"name": "get_claim", "ms": 35.0, "ok": True}),
]


def _summary(tid: str, title: str, status: str = "active") -> dict[str, Any]:
    return {"thread_id": tid, "title": title, "status": status, "updated_at": NOW, "turn_count": 1}


class FakeApi:
    """Threads keyed by identity; chat and resume replay scripted SSE events."""

    def __init__(self) -> None:
        self.threads: dict[Identity, list[dict[str, Any]]] = {
            Identity("claims_agent"): [_summary("t-agent", "Why is CLM300210 pending?")],
            Identity("customer", "CUST139920"): [_summary("t-cust", "My claim")],
        }
        self.details: dict[str, dict[str, Any]] = {
            "t-agent": {
                "thread_id": "t-agent",
                "messages": [
                    {"role": "user", "content": "Why is CLM300210 pending?"},
                    {"role": "assistant", "content": "CLM300210 is Approved, not pending."},
                ],
                "last_trace": TRACE,
                "pending_review": None,
            },
            "t-review": {
                "thread_id": "t-review",
                "messages": [{"role": "user", "content": "Analyze claim CLM300210"}],
                "last_trace": [],
                "pending_review": REVIEW,
            },
        }
        self.calls: list[tuple[Any, ...]] = []

    def health(self) -> dict[str, Any]:
        return {"status": "ok", "llm_profile": "local", "as_of": "2026-10-01", "coverage_status": "reviewed"}

    def list_threads(self, ident: Identity, limit: int = 20) -> list[dict[str, Any]]:
        self.calls.append(("list", ident))
        return self.threads.get(ident, [])

    def get_thread(self, thread_id: str, ident: Identity) -> dict[str, Any]:
        self.calls.append(("get", thread_id, ident))
        owned = {t["thread_id"] for t in self.threads.get(ident, [])} | {"t-review"}
        if thread_id not in owned or thread_id not in self.details:
            raise ApiProblem(403, "THREAD_FORBIDDEN", "This thread belongs to another identity.")
        return self.details[thread_id]

    def chat(
        self, message: str, thread_id: str | None, ident: Identity, source: str = "ui"
    ) -> Iterator[Event]:
        self.calls.append(("chat", message, thread_id, ident))
        yield "thread", {"thread_id": thread_id or "t-new"}
        yield from PROGRESS
        if message.startswith("Analyze"):
            yield "interrupt", {"assessment_summary": REVIEW}
        elif message.startswith("Claims per"):
            answer = "Health has the most claims. [sql:1a2b3c4d]"
            yield (
                "final",
                {"answer_markdown": answer, "citations": [], "trace": TRACE, "analytics": ANALYTICS},
            )
        else:
            yield "final", {"answer_markdown": f"Answer to: {message}", "citations": [], "trace": TRACE}
        yield "done", {}

    def resume(self, thread_id: str, action: str, note: str, ident: Identity) -> Iterator[Event]:
        self.calls.append(("resume", thread_id, action, note, ident))
        yield "thread", {"thread_id": thread_id}
        answer = f"Reviewer decision: **{action}**. Reviewer note: {note or '(none)'}"
        yield "final", {"answer_markdown": answer, "citations": [], "trace": TRACE}
        yield "done", {}


def _app(fake: FakeApi, **query: str) -> AppTest:
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.session_state["api"] = fake
    for key, value in query.items():
        at.query_params[key] = value
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _texts(at: AppTest) -> str:
    assert not at.exception, [e.value for e in at.exception]
    return "\n".join(m.value for m in at.markdown)


def test_AC_10_07_conversations_list_shows_only_current_identity_threads() -> None:
    at = _app(FakeApi())
    labels = [b.label for b in at.sidebar.button]
    assert any(label.startswith("Why is CLM300210 pending?") for label in labels)
    assert not any(label.startswith("My claim") for label in labels)


def test_AC_10_07_switching_persona_starts_new_conversation() -> None:
    fake = FakeApi()
    at = _app(fake, thread="t-agent")
    assert "CLM300210 is Approved, not pending." in _texts(at)
    at.sidebar.selectbox(key="persona").set_value("customer").run()
    assert at.session_state["thread_id"] is None and at.session_state["messages"] == []
    assert "thread" not in at.query_params
    assert at.query_params["persona"] == "customer" and at.query_params["principal"] == "CUST139920"
    assert fake.calls[-1] == ("list", Identity("customer", "CUST139920"))
    labels = [b.label for b in at.sidebar.button]
    assert any(label.startswith("My claim") for label in labels)
    assert not any(label.startswith("Why is CLM300210") for label in labels)


def test_AC_10_07_query_param_thread_reopens_conversation_with_last_trace() -> None:
    """A browser refresh: a fresh session whose URL carries the identity and the open thread."""
    at = _app(FakeApi(), persona="claims_agent", thread="t-agent")
    assert at.session_state["thread_id"] == "t-agent"
    assert "CLM300210 is Approved, not pending." in _texts(at)
    assert [e.label for e in at.expander] == ["How this answer was produced", "Engineer details"]


def test_AC_10_07_clicking_a_conversation_opens_it() -> None:
    at = _app(FakeApi())
    at.sidebar.button(key="open-t-agent").click().run()
    assert at.query_params["thread"] == "t-agent" and at.session_state["thread_id"] == "t-agent"
    assert "CLM300210 is Approved, not pending." in _texts(at)


def test_AC_10_07_thread_of_another_identity_is_not_opened() -> None:
    at = _app(FakeApi(), persona="customer", principal="CUST139920", thread="t-agent")
    assert at.session_state["thread_id"] is None and "thread" not in at.query_params
    assert any("Could not open" in i.value for i in at.info)


def test_AC_10_03_awaiting_review_thread_shows_card_and_approve_resumes() -> None:
    fake = FakeApi()
    at = _app(fake, thread="t-review")
    assert any("Review needed · CLM300210" in m.value for m in at.markdown)
    assert at.chat_input[0].disabled
    at.button(key="review-approve").click().run()
    assert ("resume", "t-review", "approve") in [c[:3] for c in fake.calls]
    assert at.session_state["pending_review"] is None
    assert "Reviewer decision: **approve**" in _texts(at)
    assert not at.chat_input[0].disabled


def test_AC_10_13_review_card_shows_counts_blockers_and_next_best_actions() -> None:
    at = _app(FakeApi(), thread="t-review")
    text = _texts(at)
    assert "*Blockers*" in text and "- The claim date falls outside the policy period." in text
    assert "*Next best actions*" in text and "- Request Claim Form from the customer" in text
    assert any(c.value == "5 findings · 2 blockers · 1 needs review" for c in at.caption)


def test_AC_10_14_streamlit_config_skips_email_prompt_and_usage_stats() -> None:
    import tomllib

    cfg = tomllib.loads((APP.parents[1] / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    assert cfg["browser"]["gatherUsageStats"] is False and cfg["server"]["headless"] is True


def test_AC_10_03_override_requires_a_note() -> None:
    fake = FakeApi()
    at = _app(fake, thread="t-review")
    at.button(key="review-override").click().run()
    assert not any(c[0] == "resume" for c in fake.calls)
    assert any("Add a note" in w.value for w in at.warning)
    at.text_area(key="review-note").input("Verified with hospital").run()
    at.button(key="review-override").click().run()
    assert "Reviewer note: Verified with hospital" in _texts(at)


def test_interrupt_from_chat_shows_review_card_and_badge_label() -> None:
    fake = FakeApi()
    at = _app(fake)
    at.chat_input[0].set_value("Analyze claim CLM300210").run()
    assert at.session_state["pending_review"] == REVIEW and at.session_state["thread_id"] == "t-new"
    assert at.query_params["thread"] == "t-new"
    assert any("Review needed · CLM300210" in m.value for m in at.markdown)
    fake.threads[Identity("claims_agent")].insert(0, _summary("t-new", "Analyze", "awaiting_review"))
    at.run()
    assert any(REVIEW_BADGE in b.label for b in at.sidebar.button)


def test_node_progress_events_rendered_for_each_answer() -> None:
    at = _app(FakeApi())
    at.chat_input[0].set_value("What is the maternity waiting period under Health Secure Plus?").run()
    texts = _texts(at)
    assert "Answer to: What is the maternity waiting period" in texts
    assert "▸ planner…" in texts and "✓ planner 412 ms" in texts and "🔧 `get_claim` 35 ms" in texts
    assert any(e.label.startswith("Steps · ") for e in at.expander)


def test_rejected_message_is_not_kept_and_error_is_shown() -> None:
    fake = FakeApi()

    def busy(*args: Any, **kwargs: Any) -> Iterator[Event]:
        raise ApiProblem(409, "THREAD_BUSY", "Thread is already running a turn; retry when it ends.")
        yield  # pragma: no cover

    fake.chat = busy  # type: ignore[method-assign]
    at = _app(fake)
    at.chat_input[0].set_value("hello").run()
    assert at.session_state["messages"] == []
    assert any("already running" in e.value for e in at.error)


RETRY_TURN: list[Event] = [
    ("node", {"name": "planner", "status": "start"}),
    (
        "node",
        {
            "name": "planner",
            "status": "end",
            "ms": 400.0,
            "interrupted": False,
            "plan": {
                "intents": ["policy_question"],
                "product": "Health Secure Plus",
                "claim_ids": [],
                "policy_ids": [],
            },
        },
    ),
    ("node", {"name": "synthesize", "status": "start"}),
    ("token", {"text": "bad draft with ₹99,999 ", "attempt": 1}),
    ("node", {"name": "synthesize", "status": "end", "ms": 900.0, "interrupted": False}),
    ("node", {"name": "verify", "status": "end", "ms": 2.0, "interrupted": False, "outcome": "retry"}),
    ("node", {"name": "synthesize", "status": "start"}),
    ("token", {"text": "Maternity is covered after 24 months. ", "attempt": 2}),
    ("token", {"text": "[Health Secure Plus §5 Maternity]", "attempt": 2}),
    ("node", {"name": "synthesize", "status": "end", "ms": 800.0, "interrupted": False}),
    ("node", {"name": "verify", "status": "end", "ms": 2.0, "interrupted": False, "outcome": "pass"}),
]
REVISED = "Maternity is covered after 24 months. [Health Secure Plus §5 Maternity]"


def test_AC_10_08_failed_first_draft_is_replaced_and_answer_marked_verified() -> None:
    fake = FakeApi()

    def chat(message: str, thread_id: str | None, ident: Identity, source: str = "ui") -> Iterator[Event]:
        yield "thread", {"thread_id": "t-new"}
        yield from RETRY_TURN
        yield "final", {"answer_markdown": REVISED, "citations": [], "trace": TRACE, "verified": True}
        yield "done", {}

    fake.chat = chat  # type: ignore[method-assign]
    at = _app(fake)
    at.chat_input[0].set_value("What is the maternity waiting period under Health Secure Plus?").run()
    shown = _texts(at) + " ".join(c.value for c in at.caption)
    assert REVISED in _texts(at) and "bad draft" not in shown
    assert any(c.value == "✓ verified" for c in at.caption)
    assert at.session_state["messages"][-1]["verified"] is True


def test_AC_10_08_unverified_fallback_has_no_verified_badge() -> None:
    at = _app(FakeApi())  # the default fake final carries no `verified`
    at.chat_input[0].set_value("hello there").run()
    assert "Answer to: hello there" in _texts(at)
    assert not any(c.value == "✓ verified" for c in at.caption)


def test_AC_10_09_tone_picker_hidden_for_customer() -> None:
    at = _app(FakeApi())
    assert [r.label for r in at.sidebar.radio] == ["Status tone"]
    at.sidebar.selectbox(key="persona").set_value("customer").run()
    assert not at.sidebar.radio


def test_analytics_answer_shows_chart_table_and_sql() -> None:
    at = _app(FakeApi())
    at.chat_input[0].set_value("Claims per line of business").run()
    assert "Health has the most claims." in _texts(at)
    (frame,) = _result_tables(at)  # the Trace panel has its own dataframes
    assert len(frame.value) == 3
    assert [c.value for c in at.code] == [ANALYTICS["sql"]]
    assert "SQL" in [e.label for e in at.expander]
    assert len(at.get("vega_lite_chart")) == 1
    assert any(c.value == "3 rows" for c in at.caption)


def test_plain_answer_has_no_analytics_block() -> None:
    at = _app(FakeApi())
    at.chat_input[0].set_value("What is the maternity waiting period under Health Secure Plus?").run()
    assert not _result_tables(at) and not at.code and not at.get("vega_lite_chart")


def _result_tables(at: AppTest) -> list[Any]:
    return [d for d in at.dataframe if list(d.value.columns) == ANALYTICS["columns"]]


def test_AC_10_17_customer_policy_question_renders_answer_and_trace_panel() -> None:
    """Rehearsal bug: a customer's policy question crashed after "✓ verified" while drawing the trace."""
    fake = FakeApi()
    answer = "The maternity waiting period is 9 months. [Health Secure Plus §5 Maternity]"

    def chat(message: str, thread_id: str | None, ident: Identity, source: str = "ui") -> Iterator[Event]:
        assert ident == Identity("customer", "CUST139920")
        yield "thread", {"thread_id": "t-cust-policy"}
        yield "token", {"text": answer, "attempt": 1}
        yield "final", {"answer_markdown": answer, "citations": [], "trace": POLICY_TRACE, "verified": True}
        yield "done", {}

    fake.chat = chat  # type: ignore[method-assign]
    at = _app(fake, persona="customer", principal="CUST139920")
    at.chat_input[0].set_value("What is the maternity waiting period under Health Secure Plus?").run()
    assert answer in _texts(at)
    assert any(c.value == "✓ verified" for c in at.caption)
    assert [e.label for e in at.expander][-2:] == ["How this answer was produced", "Engineer details"]
    steps = [step for df in at.dataframe if "step" in df.value for step in df.value["step"]]
    assert "Understood the question: policy question" in steps
