"""Claim dossier in the agent graph (specs 06, 07): explain vs assess, false premise, narrative as the
answer (streamed through the draft gate), completeness guard, the deterministic fallback.
Real warehouse, scripted LLM.
"""

import json
import re
from collections.abc import Callable
from typing import Any

import pytest
from fakes import citing_synth, install, plan_of, planner_script

from insurai.agent.runner import astream_resume, astream_turn, resume, run_turn
from insurai.rules.schemas import ReviewDecision

pytestmark = pytest.mark.integration

AGENT = "claims_agent"
OWNER = "CUST139920"  # owns CLM300210
CLAIM = "CLM300210"
ANALYZE_Q = "Analyze claim CLM300210 and tell me if documents are missing."
PENDING_Q = "Why is CLM300210 pending?"
SUMMARY_Q = "Give me a summary of claim CLM300210"
MIXED_Q = "Analyze claim CLM300210 and explain the maternity waiting period of Health Secure Plus"
GUARANTEE = "This claim will definitely be approved."
MANDATED = "Final decision depends on complete claim assessment."

PLANS = {
    "analyze claim clm300210 and tell": plan_of(("claim_analysis", {"claim_id": CLAIM}), question=ANALYZE_Q),
    "why is clm300210 pending": plan_of(("claim_analysis", {"claim_id": CLAIM}), question=PENDING_Q),
    "give me a summary": plan_of(("claim_analysis", {"claim_id": CLAIM}), question=SUMMARY_Q),
    "maternity waiting period": plan_of(
        ("claim_analysis", {"claim_id": CLAIM}),
        ("policy_question", {"product": "Health Secure Plus"}),
        question=MIXED_Q,
    ),
}

Responder = Callable[[list[Any]], str]


def _assessment_json(messages: list[Any]) -> dict[str, Any]:
    match = re.search(r"<assessment>(.*)</assessment>", str(messages[0].content), re.DOTALL)
    assert match, "not a narrative prompt"
    return json.loads(match.group(1))


def faithful_narrative(messages: list[Any]) -> str:
    """A model that follows dossier_narrative.md: correction, position, every finding, the actions."""
    data = _assessment_json(messages)
    lines = [data["premise_correction"]] if data.get("premise_correction") else []
    if review := data.get("review"):
        lines.append(f"The reviewer chose {review['action']}: {review['note']}")
    n = data["counts"]
    lines.append(
        f"This claim has {n['findings']} findings, {n['blockers']} of them blockers. {data['label']}"
    )
    lines += [f"- {f['message']} {f['citation']}" for f in data["findings"]]
    lines += [f"{k}. {a}" for k, a in enumerate(data["next_best_actions"], start=1)]
    return "\n".join(lines)


def lazy_narrative(messages: list[Any]) -> str:
    """A model that ignores the instructions: one cited sentence, no findings."""
    return f"Here is the claim. {_assessment_json(messages)['label']}"


def text_script(narrative: Responder, synth: Responder = citing_synth) -> Responder:
    def reply(messages: list[Any]) -> str:
        system = str(messages[0].content)
        if "<assessment>" in system and "<narrative>" not in system:
            return narrative(messages)
        if "<draft>" in system:
            draft = re.search(r"<draft>(.*)</draft>", system, re.DOTALL)
            return draft.group(1).strip() if draft else ""
        return synth(messages)

    return reply


def _install(monkeypatch: pytest.MonkeyPatch, narrative: Responder = faithful_narrative, **kw: Any) -> None:
    install(monkeypatch, {"Plan": planner_script(PLANS), "Text": text_script(narrative, **kw)})


# --- explain vs assess -----------------------------------------------------------------------------------


def test_assess_mode_interrupts_then_narrates_with_decision(
    graph: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch)
    paused = run_turn(graph, "t-assess", ANALYZE_Q, AGENT)
    assert paused.interrupt is not None
    summary = paused.interrupt
    assert summary["blockers"] and summary["next_best_actions"] and summary["counts"]["blockers"] == 2
    note = "Goodwill payment of ₹7,777 agreed"  # a number only the reviewer's note carries (V3 source)
    done = resume(graph, "t-assess", ReviewDecision(action="override", note=note))
    assert done.verification_passed is True and "The reviewer chose override: " + note in done.answer_markdown
    assert "Reviewer decision: **override**" in done.answer_markdown
    assert (
        done.assessment and done.assessment["narrative"] and done.assessment["review"]["action"] == "override"
    )


@pytest.mark.parametrize("question", [PENDING_Q, SUMMARY_Q])
def test_explain_mode_never_interrupts(graph: Any, monkeypatch: pytest.MonkeyPatch, question: str) -> None:
    _install(monkeypatch)
    result = run_turn(graph, f"t-explain-{len(question)}", question, AGENT)
    assert result.interrupt is None and result.verification_passed is True
    assert (
        result.assessment and result.assessment["needs_human_review"] is True
    )  # needs review, yet explained
    plan = graph.get_state({"configurable": {"thread_id": f"t-explain-{len(question)}"}}).values["plan"]
    assert [i.mode for i in plan.intents] == ["explain"]


def test_customer_assess_never_interrupts(graph: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch)
    result = run_turn(graph, "t-cust", ANALYZE_Q, "customer", principal_id=OWNER)
    assert result.interrupt is None
    assert "fraud" not in result.answer_markdown.lower() and "R10" not in result.answer_markdown


# --- false premise ---------------------------------------------------------------------------------------


def test_false_premise_corrected_first_with_citation(graph: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, narrative=lazy_narrative)  # the guard puts the correction first anyway
    result = run_turn(graph, "t-premise", PENDING_Q, AGENT)
    assert result.answer_markdown.startswith("CLM300210 is Approved, not pending [claims:CLM300210].")
    assert result.verification_passed is True


# --- narrative is the answer -----------------------------------------------------------------------------


def test_AC_07_07_completeness_guard_appends_unmentioned_findings(
    graph: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch, narrative=lazy_narrative)
    result = run_turn(graph, "t-lazy", SUMMARY_Q, AGENT)
    assessment = result.assessment
    assert assessment is not None
    for rule in assessment["rules"]:
        if rule["status"] in ("fail", "review"):
            assert rule["message"] in result.answer_markdown, rule["id"]
    for action in assessment["next_best_actions"]:
        assert action in result.answer_markdown
    assert "₹58,119" in result.answer_markdown  # CA001: expected payable in the R09 finding
    assert result.verification_passed is True


def test_narrative_is_the_answer_without_a_second_generator_call(
    graph: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def synth(messages: list[Any]) -> str:
        calls.append("synthesize")
        return citing_synth(messages)

    _install(monkeypatch, synth=synth)
    result = run_turn(graph, "t-pass", SUMMARY_Q, AGENT)
    assert calls == [] and result.assessment
    assert result.answer_markdown.startswith(result.assessment["narrative"])


def test_mixed_turn_still_synthesizes(graph: Any, monkeypatch: pytest.MonkeyPatch, index_path: Any) -> None:
    calls: list[str] = []

    def synth(messages: list[Any]) -> str:
        calls.append("synthesize")
        assert 'kind="ClaimAssessment"' in str(messages[0].content)  # the narrative is evidence
        return citing_synth(messages)

    _install(monkeypatch, synth=synth)
    paused = run_turn(graph, "t-mixed", MIXED_Q, AGENT)
    result = resume(graph, "t-mixed", ReviewDecision(action="approve")) if paused.interrupt else paused
    assert calls == ["synthesize"] and result.verification_passed is True


def test_failed_verification_falls_back_to_rendered_assessment(
    graph: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both attempts fail V3 (an invented amount): the answer is the assessment rendered without an LLM,
    never the policy-wording abstention."""

    def invents(messages: list[Any]) -> str:
        return f"The payable is ₹12,34,567. [claims:{CLAIM}]"

    _install(monkeypatch, narrative=lambda m: invents(m) + "\n" + faithful_narrative(m), synth=invents)
    result = run_turn(graph, "t-fallback", SUMMARY_Q, AGENT)
    assert "policy documents" not in result.answer_markdown.lower()
    assert result.answer_markdown.startswith("Claim CLM300210 is Approved; the assessment found")
    assert "Next steps:" in result.answer_markdown and "12,34,567" not in result.answer_markdown
    events = [e for e in result.trace if e.kind == "verify"]
    assert [e.data["outcome"] for e in events] == ["retry", "abstain"]


# --- streaming -------------------------------------------------------------------------------------------


async def _collect(graph: Any, thread_id: str, message: str) -> list[tuple[str, Any]]:
    return [e async for e in astream_turn(graph, thread_id, message, AGENT)]


def _tokens(events: list[tuple[str, Any]]) -> str:
    return "".join(d["text"] for n, d in events if n == "token")


async def test_claim_analysis_turn_streams_narrative_tokens(
    graph: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch)
    events = await _collect(graph, "t-stream", SUMMARY_Q)
    final = events[-1][1]
    streamed = _tokens(events)
    assert streamed and final.answer_markdown.startswith(streamed.strip()[:40])
    assert {d["attempt"] for n, d in events if n == "token"} == {1}


async def test_streamed_after_resume(graph: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch)
    first = await _collect(graph, "t-stream-resume", ANALYZE_Q)
    assert _tokens(first) == "" and first[-1][1].interrupt is not None
    resumed = [e async for e in astream_resume(graph, "t-stream-resume", ReviewDecision(action="approve"))]
    assert _tokens(resumed)


async def test_guarantee_phrase_in_scripted_narrative_never_streamed(
    graph: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch, narrative=lambda m: f"{GUARANTEE}\n" + faithful_narrative(m))
    events = await _collect(graph, "t-guarantee", SUMMARY_Q)
    assert "definitely be approved" not in _tokens(events)
    assert ("draft_hidden", {"attempt": 1, "reason": "guarantee"}) in events
    final = events[-1][1]
    assert "definitely" not in final.answer_markdown and MANDATED in final.answer_markdown


async def test_mixed_turn_does_not_stream_the_narrative(
    graph: Any, monkeypatch: pytest.MonkeyPatch, index_path: Any
) -> None:
    _install(monkeypatch, narrative=lambda m: "NARRATIVE-ONLY " + faithful_narrative(m))
    events = await _collect(graph, "t-stream-mixed", MIXED_Q.replace("Analyze claim", "Summarise claim"))
    assert "NARRATIVE-ONLY" not in _tokens(events)
