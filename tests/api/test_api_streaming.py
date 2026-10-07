"""/chat streaming (spec 09): token order, retries, never streaming a promise or a <think> block,
heartbeats, the plan summary and tool_start events. Real warehouse, scripted streaming LLMs."""

import json
import time
from typing import Any

import pytest
from fakes import citing_synth, install, plan_of, planner_script
from fastapi.testclient import TestClient
from sse_client import AGENT, OWNER, OWNER_ID, stream

from insurai.settings import get_settings
from insurai.tools.base import fetch_one

pytestmark = pytest.mark.integration

# Planner path with a generator answer: claim_interactions has no template answer (spec 06), and a why
# question would be promoted to claim_analysis (rule 10).
WHY = "Who contacted us about CLM300210 recently?"
CONTACTS = plan_of(
    ("claim_interactions", {"claim_id": "CLM300210"}), question="Who contacted us about CLM300210?"
)
MANDATED = "Final decision depends on complete claim assessment."


def _script(monkeypatch: pytest.MonkeyPatch, synth: Any, planner: Any = None) -> None:
    install(monkeypatch, {"Plan": planner or planner_script({"who contacted": CONTACTS}), "Text": synth})


def _names(events: list[tuple[str, Any]]) -> list[str]:
    return [name for name, _ in events]


def _tokens(events: list[tuple[str, Any]], attempt: int | None = None) -> list[str]:
    return [d["text"] for n, d in events if n == "token" and attempt in (None, d["attempt"])]


def _synth_windows(events: list[tuple[str, Any]]) -> list[tuple[int, int]]:
    starts = [
        i for i, (n, d) in enumerate(events) if n == "node" and d == {"name": "synthesize", "status": "start"}
    ]
    ends = [
        i
        for i, (n, d) in enumerate(events)
        if n == "node" and d["name"] == "synthesize" and d["status"] == "end"
    ]
    return list(zip(starts, ends, strict=True))


def test_AC_09_13_event_order_thread_nodes_tokens_final_done(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _script(monkeypatch, citing_synth)
    status, events = stream(client, "/chat", {"message": WHY}, AGENT)
    assert status == 200
    names = _names(events)
    assert names[0] == "thread" and names[-2:] == ["final", "done"] and names.count("final") == 1
    assert set(names[1:-2]) <= {"node", "tool_start", "tool", "heartbeat", "token"}
    windows = _synth_windows(events)
    token_at = [i for i, n in enumerate(names) if n == "token"]
    assert token_at and all(any(s < i < e for s, e in windows) for i in token_at)
    final = events[-2][1]
    assert final["verified"] is True and "".join(_tokens(events)) == final["answer_markdown"]


def test_AC_09_13_retry_streams_a_second_attempt_after_verify_retry(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    replies = iter(["Payable is ₹99,999. [claims:CLM300210]"])

    def synth(messages: list[Any]) -> str:
        return next(replies, None) or citing_synth(messages)

    _script(monkeypatch, synth)
    _, events = stream(client, "/chat", {"message": WHY}, AGENT)
    verify_ends = [
        i for i, (n, d) in enumerate(events) if n == "node" and d["name"] == "verify" and d["status"] == "end"
    ]
    assert [events[i][1]["outcome"] for i in verify_ends] == ["retry", "pass"]
    first, second = _tokens(events, 1), _tokens(events, 2)
    assert "99,999" in "".join(first) and second
    last_first = max(i for i, (n, d) in enumerate(events) if n == "token" and d["attempt"] == 1)
    first_second = min(i for i, (n, d) in enumerate(events) if n == "token" and d["attempt"] == 2)
    assert last_first < verify_ends[0] < first_second
    assert events[-2][1]["answer_markdown"] == "".join(second) and events[-2][1]["verified"] is True


def test_AC_09_13_a_promise_is_never_streamed_and_final_has_mandated_wording(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = (
        "Here is what the records show for this claim right now. [interactions:CLM300210] "
        "Your claim will definitely be approved. [interactions:CLM300210]"
    )
    _script(monkeypatch, lambda messages: text)
    _, events = stream(client, "/chat", {"message": WHY}, AGENT)
    streamed = "".join(_tokens(events))
    assert "definitely" not in streamed and "will definitely be approved" not in streamed
    assert [d for n, d in events if n == "draft_hidden"] == [{"attempt": 1, "reason": "guarantee"}]
    final = events[-2][1]
    assert MANDATED in final["answer_markdown"] and "definitely" not in final["answer_markdown"]


def test_AC_09_13_think_block_is_never_streamed(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _script(monkeypatch, lambda messages: "<think>private reasoning here</think>" + citing_synth(messages))
    _, events = stream(client, "/chat", {"message": WHY}, AGENT)
    assert "private" not in "".join(_tokens(events)) and _tokens(events)
    assert "private" not in events[-2][1]["answer_markdown"]


def test_AC_09_14_heartbeat_every_interval_while_the_planner_runs(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def slow_planner(messages: list[Any]) -> Any:
        time.sleep(0.35)
        return CONTACTS

    monkeypatch.setattr(get_settings().agent, "heartbeat_s", 0.1)
    _script(monkeypatch, citing_synth, planner=slow_planner)
    _, events = stream(client, "/chat", {"message": WHY}, AGENT)
    beats = [d for n, d in events if n == "heartbeat"]
    planner_beats = [b for b in beats if b["node"] == "planner"]
    assert 2 <= len(planner_beats) <= 4
    assert [b["beat"] for b in planner_beats] == list(range(1, len(planner_beats) + 1))
    assert all(b["elapsed_ms"] >= b["beat"] * 100 - 1 for b in planner_beats)
    assert {b["node"] for b in beats} <= {"planner", "claim_tools", "synthesize", "verify"}


def test_AC_09_15_planner_end_carries_safe_plan_summary_and_no_customer_name(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = fetch_one("select customer_name from silver.customers where customer_id = ?", [OWNER_ID])
    assert name and name["customer_name"]
    _script(monkeypatch, citing_synth)
    _, events = stream(client, "/chat", {"message": WHY}, OWNER)
    planner_end = next(
        d for n, d in events if n == "node" and d["name"] == "planner" and d["status"] == "end"
    )
    assert planner_end["plan"] == {
        "intents": ["claim_interactions"],
        "product": None,
        "claim_ids": ["CLM300210"],
        "policy_ids": [],
    }
    live = json.dumps([e for e in events if e[0] != "final"], ensure_ascii=False)
    assert name["customer_name"] not in live and OWNER_ID not in live


def test_AC_09_15_fast_path_resolve_context_carries_the_plan(client: TestClient) -> None:
    _, events = stream(client, "/chat", {"message": "status of CLM300210"}, AGENT)
    end = next(
        d for n, d in events if n == "node" and d["name"] == "resolve_context" and d["status"] == "end"
    )
    assert end["plan"]["intents"] == ["claim_status"] and end["plan"]["claim_ids"] == ["CLM300210"]
    assert "token" not in _names(events)


def test_AC_09_16_tool_start_precedes_the_tool_event_with_safe_args(client: TestClient) -> None:
    _, events = stream(client, "/chat", {"message": "status of CLM300210"}, AGENT)
    names = _names(events)
    start = names.index("tool_start")
    assert events[start][1] == {"name": "get_claim", "args_redacted": {"claim_id": "CLM300210"}}
    assert start < names.index("tool")
