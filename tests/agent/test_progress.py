"""Draft gate (never stream a promise, no <think>), plan summary and status-safe arguments (spec 09)."""

import asyncio
import re
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fakes import plan_of

from insurai.agent.progress import DraftGate, holdback_chars, holdback_for, plan_summary
from insurai.api.streaming import with_heartbeats
from insurai.observability.progress import emit_progress, status_args
from insurai.tools.messages import guardrails

pytestmark = pytest.mark.unit

SAFE = (
    "Claim CLM300210 is under review by the claims team at the moment. [claims:CLM300210] "
    "The discharge summary is still missing from the file. [claim_documents:CLM300210] "
)
PROMISE = "Once it arrives, your claim will definitely be approved. [claims:CLM300210]"


def _run(gate: DraftGate, chunks: list[str]) -> list[tuple[str, dict[str, Any]]]:
    events = [e for chunk in chunks for e in gate.feed(chunk)]
    return events + gate.close()


def _tokens(events: list[tuple[str, dict[str, Any]]]) -> str:
    return "".join(d["text"] for name, d in events if name == "token")


def test_AC_09_13_holdback_covers_the_longest_guarantee_match() -> None:
    import re._parser as parser  # stdlib parser: a pattern's maximum match width

    widths = [parser.parse(p).getwidth()[1] for p in guardrails()["no_guarantee"]["patterns"]]
    assert holdback_chars() >= max(widths)


def test_AC_08_23_holdback_is_the_longest_guarantee_match_plus_the_margin() -> None:
    import re._parser as parser

    cfg = guardrails()["no_guarantee"]
    longest = max(parser.parse(p, re.IGNORECASE).getwidth()[1] for p in cfg["patterns"])
    assert holdback_chars() == longest + cfg["stream_holdback_margin"]
    assert holdback_chars() < 64  # shorter than the old fixed hold-back: earlier first token


def test_AC_08_23_unbounded_pattern_falls_back_to_the_cap() -> None:
    assert holdback_for([r"\bassure you\b", r"guarantee.*approved"], margin=8, cap=64) == 64
    assert holdback_for([r"\bassure you\b"], margin=8, cap=64) == 18
    assert holdback_for([r"x{100}"], margin=8, cap=64) == 64


@pytest.mark.parametrize("split", range(1, len(SAFE + PROMISE)))
def test_AC_09_13_promise_never_streams_at_any_chunk_boundary(split: int) -> None:
    text = SAFE + PROMISE
    events = _run(DraftGate(1), [text[:split], text[split:]])
    streamed = _tokens(events)
    assert "definitely" not in streamed and "will" not in streamed
    assert [name for name, _ in events].count("draft_hidden") == 1
    assert (SAFE + PROMISE).startswith(streamed)  # safe text before the phrase may stream


def test_AC_09_13_promise_streamed_word_by_word_hides_once() -> None:
    words = re.findall(r"\S+\s*", SAFE + PROMISE)
    events = _run(DraftGate(2), words)
    assert _tokens(events) and "definitely" not in _tokens(events)
    hidden = [d for name, d in events if name == "draft_hidden"]
    assert hidden == [{"attempt": 2, "reason": "guarantee"}]
    assert events[-1][0] == "draft_hidden"  # nothing streams after the hit


def test_AC_09_13_safe_draft_is_released_in_full_and_lags_the_holdback() -> None:
    words = re.findall(r"\S+\s*", SAFE)
    gate = DraftGate(1)
    released = ""
    for word in words:
        released += _tokens(gate.feed(word))
        assert len(released) <= len(gate.raw) - min(gate.holdback, len(gate.raw))
    assert released and released + _tokens(gate.close()) == SAFE


def test_AC_09_13_think_block_never_streams() -> None:
    text = "<think>internal musing about the customer</think>" + SAFE
    events = _run(DraftGate(1), re.findall(r"\S+\s*|\s+", text))
    assert "musing" not in _tokens(events) and _tokens(events) == SAFE


def test_AC_09_13_unclosed_think_hides_the_attempt() -> None:
    events = _run(DraftGate(1), ["<think>still ", "thinking about it " * 10])
    assert _tokens(events) == ""
    assert events == [("draft_hidden", {"attempt": 1, "reason": "reasoning"})]


def test_AC_09_13_each_attempt_has_its_own_gate() -> None:
    first = _run(DraftGate(1), [SAFE + PROMISE])
    second = _run(DraftGate(2), [SAFE])
    assert [n for n, _ in first] == ["draft_hidden"]
    assert all(d["attempt"] == 2 for n, d in second if n == "token") and _tokens(second) == SAFE


def test_AC_09_15_plan_summary_keeps_ids_and_canonical_product_only() -> None:
    plan = plan_of(
        ("policy_question", {"product": "health secure plus"}),
        ("claim_status", {"claim_id": "CLM300210", "customer_id": "CUST139920"}),
        ("hospital_check", {"hospital_name": "Aditya Joshi Clinic", "city": "Pune"}),
        ("policy_details", {"policy_id": "not-an-id"}),
    )
    assert plan_summary(plan) == {
        "intents": ["policy_question", "claim_status", "hospital_check", "policy_details"],
        "product": "Health Secure Plus",
        "claim_ids": ["CLM300210"],
        "policy_ids": [],
    }


def test_AC_09_16_status_args_drop_names_free_text_and_unknown_products() -> None:
    args = {
        "claim_id": "CLM300210",
        "policy_id": "Aditya Joshi",
        "hospital_id": "HOSP1257",
        "product": "Aditya Joshi",
        "name": "Aditya Joshi",
        "query": "maternity waiting period",
        "city": "Pune",
    }
    assert status_args(args) == {"claim_id": "CLM300210", "hospital_id": "HOSP1257"}


def test_AC_09_16_emit_progress_outside_a_graph_run_is_a_no_op() -> None:
    assert emit_progress("tool_start", {"name": "get_claim", "args_redacted": {}}) is None


async def _slow_run(steps: list[tuple[float, str, dict[str, Any]]]) -> AsyncIterator[tuple[str, Any]]:
    for delay, kind, data in steps:
        await asyncio.sleep(delay)
        yield kind, data


async def test_AC_09_14_heartbeat_every_interval_while_a_node_runs() -> None:
    interval = 0.05
    run = _slow_run(
        [
            (0, "node", {"name": "planner", "status": "start"}),
            (0.18, "node", {"name": "planner", "status": "end"}),
            (0, "node", {"name": "respond", "status": "start"}),
            (0.01, "node", {"name": "respond", "status": "end"}),
        ]
    )
    events = [e async for e in with_heartbeats(run, interval)]
    beats = [d for name, d in events if name == "heartbeat"]
    assert {b["node"] for b in beats} == {"planner"}  # a node shorter than the interval gets none
    assert 2 <= len(beats) <= 4 and [b["beat"] for b in beats] == list(range(1, len(beats) + 1))
    assert all(b["elapsed_ms"] >= b["beat"] * interval * 1000 - 1 for b in beats)
    end = next(
        i for i, (n, d) in enumerate(events) if n == "node" and d == {"name": "planner", "status": "end"}
    )
    assert all(i < end for i, (n, _) in enumerate(events) if n == "heartbeat")


async def test_with_heartbeats_reraises_the_run_error() -> None:
    async def failing() -> AsyncIterator[tuple[str, Any]]:
        yield "node", {"name": "planner", "status": "start"}
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        _ = [e async for e in with_heartbeats(failing(), 0.05)]
