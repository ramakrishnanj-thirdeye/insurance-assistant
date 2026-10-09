"""Spec 08 through the graph (warehouse and private index): guarantee answers, pinned §14/§15, conflict
rendering, V6 retry for a customer, log redaction. Scripted models only (no network)."""

import json
import logging
from datetime import date
from typing import Any

import pytest
from fakes import citing_synth, install, plan_of, planner_script

from insurai.agent.runner import run_turn
from insurai.retrieval import search
from insurai.tools.messages import guardrails, refusal
from insurai.tools.schemas import ToolContext

pytestmark = pytest.mark.integration

MANDATED = "Final decision depends on complete claim assessment."
S15 = "[All products §15 Training FAQ Q1]"
PRECEDENCE = (
    "Your policy schedule governs this policy's numbers; the product wording describes the general terms."
)
PROMISE = "Under Health Secure Plus, can you promise my hospital bill will be paid in full?"


def _verify_events(result: Any) -> list[Any]:
    return [e for e in result.trace if e.kind == "verify"]


@pytest.mark.usefixtures("index_path")
def test_AC_08_06_guarantee_CLM300500_answers_with_s15_and_needs(
    graph: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    question = "Guarantee that CLM300500 will be approved"
    status_only = plan_of(("claim_status", {"claim_id": "CLM300500"}), question=question)
    install(monkeypatch, {"Plan": planner_script({"guarantee": status_only}), "Text": citing_synth})
    result = run_turn(graph, "t-ac0806", question, "claims_agent")
    answer = result.answer_markdown
    assert refusal("GUARANTEE_REQUEST") not in answer and result.interrupt is None
    assert MANDATED in answer and S15 in answer
    assert "What claim CLM300500 still needs:" in answer or "No documents are missing" in answer
    plan = next(e for e in result.trace if e.kind == "intent" and e.name == "plan")
    assert plan.data["guarantee_request"] and plan.data["guarantee_added"] == [
        "claim_analysis",
        "policy_question",
    ]
    assert not any(e.kind == "intent" and e.name == "fast_path" for e in result.trace)
    assert result.verification_passed


@pytest.mark.usefixtures("index_path")
def test_AC_08_14_pinned_sections_reach_s15_where_search_alone_does_not() -> None:
    ctx = ToolContext(persona="claims_agent", principal_id=None, as_of=date(2026, 10, 1), trace_id="t-pin")
    plain = search.search_policy(ctx, PROMISE, product="Health Secure Plus")
    assert all(c.chunk.section_no != 15 for c in plain.chunks), "premise: search alone misses §15"
    pinned = search.search_policy(ctx, PROMISE, product="Health Secure Plus", pinned_sections=[14, 15])
    via = {c.chunk.chunk_id: c.via for c in pinned.chunks}
    assert {k for k, v in via.items() if v == "pinned"} >= {
        "all-s14",
        "all-s15-q1",
        "all-s15-q2",
        "all-s15-q3",
    }
    assert [c.chunk.chunk_id for c in pinned.chunks[: len(plain.chunks)]] == [
        c.chunk.chunk_id for c in plain.chunks
    ]
    assert S15 in {s.label for s in pinned.sources}


@pytest.mark.usefixtures("index_path")
def test_AC_08_14_guarantee_turn_cites_s15_from_the_pinned_chunks(
    graph: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = plan_of(("policy_question", {"product": "Health Secure Plus"}), question=PROMISE)
    install(
        monkeypatch,
        {
            "Plan": [plan],
            "Text": lambda m: (
                "Cashless claims need pre-authorisation. [Health Secure Plus §10 Claim Procedure]"
            ),
        },
    )
    result = run_turn(graph, "t-ac0814", PROMISE, "claims_agent")
    assert result.answer_markdown.startswith(f"I can't promise an outcome. {MANDATED} {S15}")
    assert result.verification_passed


@pytest.mark.usefixtures("index_path")
def test_AC_08_09_conflict_rendering_scripted(graph: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Health Secure Plus policy POL200025 has a schedule waiting period of 0 days; §4 says 30 days. The
    scripted synthesizer leaves the conflict out; the deterministic completion renders it."""
    question = "What's the waiting period on POL200025?"
    plan = plan_of(
        ("policy_details", {"policy_id": "POL200025"}),
        ("policy_question", {"product": "Health Secure Plus"}),
        question=question,
    )
    install(monkeypatch, {"Plan": [plan], "Text": citing_synth})
    result = run_turn(graph, "t-ac0809", question, "claims_agent")
    answer = result.answer_markdown
    assert "0 days in your policy schedule [policies:POL200025]" in answer
    assert "30 days in the product wording [Health Secure Plus §4 Waiting Period]" in answer
    assert PRECEDENCE in answer and guardrails()["conflict_rendering"]["precedence_sentence"] == PRECEDENCE
    assert result.verification_passed


def test_AC_08_07_customer_fraud_score_is_retried_into_a_polite_answer(
    graph: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CUST147306 owns CLM300500 (fraud score 0.218, hidden from customers). A draft that states the score
    fails V6 and is retried with the V6 feedback; the shown answer has no score."""
    question = "What is my fraud score on CLM300500?"
    plan = plan_of(("claim_interactions", {"claim_id": "CLM300500"}), question=question)
    leaky = "Your fraud score is 0.218. [interactions:CLM300500]"
    polite = (
        "I can't share internal assessment details, but here is your claim's contact history. "
        "[interactions:CLM300500]"
    )
    prompts: list[str] = []

    def synth(messages: Any) -> str:
        prompts.append(str(messages[0].content))
        return leaky if len(prompts) == 1 else polite

    install(monkeypatch, {"Plan": [plan], "Text": synth})
    result = run_turn(graph, "t-ac0807", question, "customer", "CUST147306")
    first, last = _verify_events(result)[0], _verify_events(result)[-1]
    v6 = next(c for c in first.data["checks"] if c["check"] == "V6")
    assert not v6["passed"] and "fraud score value" in v6["detail"]
    assert "never mention fraud scores" in prompts[1]
    assert last.data["outcome"] == "pass" and result.answer_markdown == polite
    assert "0.218" not in result.answer_markdown


def test_AC_08_08_logs_hold_no_raw_aadhaar_pan_phone(
    graph: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    raw = {"aadhaar": "2345 6789 0123", "pan": "ABCDE1234F", "phone": "9876543210"}
    message = (
        f"Status of CLM300210 please. My Aadhaar is {raw['aadhaar']}, PAN {raw['pan']}, phone {raw['phone']}."
    )
    plan = plan_of(("claim_status", {"claim_id": "CLM300210"}), question=message)
    install(monkeypatch, {"Plan": [plan], "Text": citing_synth})
    root = logging.getLogger("insurai")
    root.addHandler(caplog.handler)  # the insurai namespace does not propagate to the root logger
    try:
        with caplog.at_level(logging.DEBUG, logger="insurai"):
            result = run_turn(graph, "t-ac0808", message, "customer", "CUST139920")
    finally:
        root.removeHandler(caplog.handler)
    trace = json.dumps([e.model_dump(mode="json") for e in result.trace], ensure_ascii=False)
    assert caplog.records, "expected log records from the turn"
    for value in raw.values():
        assert value not in caplog.text and value not in trace and value not in result.answer_markdown


@pytest.mark.usefixtures("index_path")
def test_AC_08_09_conflict_rendering_scripted_policy_details_only(
    graph: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """qwen3:8b routes the question to policy_details alone (seen 2026-10-09): the worker adds the product's
    waiting-period coverage cell, and the template answer gains the conflict line."""
    question = "What's the waiting period on POL200025?"
    plan = plan_of(("policy_details", {"policy_id": "POL200025"}), question=question)
    install(monkeypatch, {"Plan": [plan]})
    result = run_turn(graph, "t-ac0809b", question, "claims_agent")
    answer = result.answer_markdown
    assert "0 days in your policy schedule [policies:POL200025]" in answer
    assert "30 days in the product wording [Health Secure Plus §4 Waiting Period]" in answer
    assert PRECEDENCE in answer and result.verification_passed
    assert not any(e.kind == "llm" and e.name == "synthesize" for e in result.trace)
