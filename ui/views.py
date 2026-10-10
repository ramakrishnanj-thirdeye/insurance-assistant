"""Pure display helpers for the Streamlit pages (no Streamlit import, unit-tested).

Relative times use the wall clock: thread timestamps are metadata (spec 09), not business dates, so the
as-of-date rule does not apply here.
"""

import json
from datetime import UTC, datetime
from typing import Any

from insurai.tools.access import load_personas

WAIT_CAPTION = "Please wait for the answer before switching conversations"
REVIEW_BADGE = "⏳ review pending"
DETAIL_MAX = 160


def parse_time(value: str | datetime) -> datetime:
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def relative_time(value: str | datetime, now: datetime | None = None) -> str:
    seconds = ((now or datetime.now(UTC)) - parse_time(value)).total_seconds()
    if seconds < 60:
        return "just now"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} h ago"
    days = hours // 24
    if days == 1:
        return "yesterday"
    return f"{days} days ago"


def progress_line(event: str, data: dict[str, Any]) -> str:
    """One line per streamed node or tool event."""
    name = data.get("name", "?")
    if event == "tool":
        mark = "🔧" if data.get("ok", True) else "🔧 ✗"
        return f"{mark} `{name}` {data.get('ms', 0):.0f} ms"
    if data.get("status") == "start":
        return f"▸ {name}…"
    suffix = " (paused for review)" if data.get("interrupted") else ""
    return f"✓ {name} {data.get('ms', 0):.0f} ms{suffix}"


def thread_label(summary: dict[str, Any], now: datetime | None = None) -> str:
    label = f"{summary.get('title') or 'Untitled'} · {relative_time(summary['updated_at'], now)}"
    if summary.get("status") == "awaiting_review":
        label += f" · {REVIEW_BADGE}"
    return label


def compact(data: dict[str, Any], limit: int = DETAIL_MAX) -> str:
    """Scalar fields of a trace event's data as short JSON; lists and dicts are rendered separately."""
    scalars = {k: v for k, v in data.items() if not isinstance(v, list | dict) and k != "sql"}
    text = json.dumps(scalars, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def duration_ms(event: dict[str, Any]) -> float:
    return round(float(event.get("end_ms", 0)) - float(event.get("start_ms", 0)), 1)


def review_counts(review: dict[str, Any]) -> str | None:
    """The review card's summary line, e.g. "12 findings · 3 blockers · 2 need review"."""
    counts = review.get("counts")
    if not isinstance(counts, dict):
        return None
    parts = [
        f"{counts[key]} {label if counts[key] == 1 else plural}"
        for key, label, plural in (
            ("findings", "finding", "findings"),
            ("blockers", "blocker", "blockers"),
            ("needs_review", "needs review", "need review"),
        )
        if isinstance(counts.get(key), int)
    ]
    return " · ".join(parts) or None


def page_keys(persona: str) -> list[str]:
    """Pages per persona: Chat always, Claim Dossier for staff, Eval Dashboard if it may read reports."""
    keys = ["chat"]
    if persona in ("claims_agent", "supervisor"):
        keys.append("dossier")
    if load_personas()[persona].can_read_eval_reports:
        keys.append("eval")
    return keys
