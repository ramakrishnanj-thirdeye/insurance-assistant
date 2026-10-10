"""Pure display helpers of the Streamlit pages."""

from datetime import UTC, datetime, timedelta

import pytest
from views import REVIEW_BADGE, compact, progress_line, relative_time, thread_label

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("delta", "text"),
    [
        (timedelta(seconds=10), "just now"),
        (timedelta(minutes=5), "5 min ago"),
        (timedelta(hours=3), "3 h ago"),
        (timedelta(days=1, hours=2), "yesterday"),
        (timedelta(days=4), "4 days ago"),
    ],
)
def test_relative_time(delta: timedelta, text: str) -> None:
    assert relative_time(NOW - delta, NOW) == text


def test_relative_time_accepts_iso_strings_without_zone() -> None:
    assert relative_time("2026-10-06T11:58:00", NOW) == "2 min ago"


def test_progress_lines() -> None:
    assert progress_line("node", {"name": "planner", "status": "start"}) == "▸ planner…"
    assert progress_line("node", {"name": "planner", "status": "end", "ms": 412.3}) == "✓ planner 412 ms"
    paused = progress_line("node", {"name": "claim_dossier", "status": "end", "ms": 9, "interrupted": True})
    assert paused.endswith("(paused for review)")
    assert progress_line("tool", {"name": "get_claim", "ms": 35.2, "ok": True}) == "🔧 `get_claim` 35 ms"
    assert "✗" in progress_line("tool", {"name": "get_claim", "ms": 1, "ok": False})


def test_thread_label_badges_awaiting_review() -> None:
    summary = {"title": "Analyze claim", "status": "awaiting_review", "updated_at": NOW.isoformat()}
    assert thread_label(summary, NOW) == f"Analyze claim · just now · {REVIEW_BADGE}"
    assert REVIEW_BADGE not in thread_label({**summary, "status": "active"}, NOW)


def test_compact_keeps_scalars_and_truncates() -> None:
    assert compact({"a": 1, "rows": [{"x": 1}], "sql": "SELECT 1"}) == '{"a": 1}'
    assert compact({"a": "x" * 500}, limit=20).endswith("…")


def test_AC_10_13_review_counts_line() -> None:
    from views import review_counts

    assert review_counts({"counts": {"findings": 1, "blockers": 0, "needs_review": 2}}) == (
        "1 finding · 0 blockers · 2 need review"
    )
    assert review_counts({}) is None
