"""The TurnView draft state machine (spec 10): drafting, checking, revising, verified, fallback."""

import pytest

from insurai.api.client import TurnView

pytestmark = pytest.mark.unit

SYN_START = ("node", {"name": "synthesize", "status": "start"})
SYN_END = ("node", {"name": "synthesize", "status": "end", "ms": 5.0})


def _verify_end(outcome: str) -> tuple[str, dict]:
    return ("node", {"name": "verify", "status": "end", "ms": 1.0, "outcome": outcome})


def _phases(events: list[tuple[str, dict]]) -> tuple[TurnView, list[tuple[str, str]]]:
    view, seen = TurnView(), []
    for event, data in events:
        view.apply(event, data)
        seen.append((view.phase, view.draft_text))
    return view, seen


def test_AC_10_08_draft_streams_then_checks_then_verified() -> None:
    view, seen = _phases(
        [
            SYN_START,
            ("token", {"text": "Covered ", "attempt": 1}),
            ("token", {"text": "after 24 months.", "attempt": 1}),
            SYN_END,
            _verify_end("pass"),
            ("final", {"answer_markdown": "Covered after 24 months.", "verified": True}),
        ]
    )
    assert seen[1:4] == [
        ("drafting", "Covered "),
        ("drafting", "Covered after 24 months."),
        ("checking", "Covered after 24 months."),
    ]
    assert view.phase == "verified" and view.verified and view.draft_text == ""
    assert view.answer == "Covered after 24 months."


def test_AC_10_08_failed_first_attempt_is_replaced_by_the_revision() -> None:
    view, seen = _phases(
        [
            SYN_START,
            ("token", {"text": "bad draft ₹99,999", "attempt": 1}),
            SYN_END,
            _verify_end("retry"),
            SYN_START,
            ("token", {"text": "good draft", "attempt": 2}),
            SYN_END,
            _verify_end("pass"),
            ("final", {"answer_markdown": "good draft", "verified": True}),
        ]
    )
    assert seen[3] == ("revising", "")  # the failed draft is cleared at once
    assert seen[5] == ("revising", "good draft")
    assert all("bad" not in text for _, text in seen[3:])
    assert view.answer == "good draft" and view.phase == "verified"


def test_AC_10_08_retry_then_abstain_shows_the_fallback() -> None:
    fallback = "The policy documents don't address this directly."
    view, _ = _phases(
        [
            ("token", {"text": "bad", "attempt": 1}),
            SYN_END,
            _verify_end("retry"),
            ("token", {"text": "still bad", "attempt": 2}),
            SYN_END,
            _verify_end("abstain"),
            ("final", {"answer_markdown": fallback, "verified": False}),
        ]
    )
    assert view.phase == "final" and not view.verified and view.draft_text == ""
    assert view.answer == fallback


def test_AC_10_08_hidden_draft_shows_nothing_until_final() -> None:
    _, seen = _phases(
        [
            ("token", {"text": "Here is ", "attempt": 1}),
            ("draft_hidden", {"attempt": 1, "reason": "guarantee"}),
            ("token", {"text": "late", "attempt": 1}),
            SYN_END,
        ]
    )
    assert seen[1:] == [("checking", ""), ("checking", ""), ("checking", "")]
