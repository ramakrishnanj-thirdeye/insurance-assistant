"""Agent graph acceptance tests against the real warehouse, with scripted LLM outputs (no network)."""

from typing import Any

import pytest
from fakes import citing_synth, forbid_llm, history_turns, install, plan_of, planner_script

from insurai.agent.prompts import load_prompt, template
from insurai.agent.runner import NoPendingReview, ReviewPending, resume, run_turn
from insurai.guardrails.verify import number_tokens, verify
from insurai.observability.callbacks import LLMCallRecorder
from insurai.rules.schemas import ReviewDecision

pytestmark = pytest.mark.integration

AGENT = "claims_agent"
OWNER = "CUST139920"  # owns CLM300210
NOTE = "Hospital confirmed the admission by phone"


def _plans(**table: Any) -> dict[str, Any]:
    return {key.replace("_", " "): plan for key, plan in table.items()}


ANALYZE = plan_of(("claim_analysis", {"claim_id": "CLM300210"}), question="Analyze claim CLM300210")
DOCS_FOLLOW_UP = plan_of(
    ("claim_documents", {}), question="Which documents are missing for the active claim?"
)
# claim_interactions has no template answer, so it exercises synthesis (spec 06 template answers).
CONTACTS_FOLLOW_UP = plan_of(("claim_interactions", {}), question="Who contacted us about the active claim?")


def _install_scripts(monkeypatch: pytest.MonkeyPatch) -> None:
    install(
        monkeypatch,
        {
            "Plan": planner_script(
                {
                    "analyze": ANALYZE,
                    "which documents are missing": DOCS_FOLLOW_UP,
                    "contacts": CONTACTS_FOLLOW_UP,
                }
            ),
            "Text": citing_synth,
        },
    )


def test_AC_06_05_fast_path_zero_llm_calls(graph: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    forbid_llm(monkeypatch)
    recorder = LLMCallRecorder()
    result = run_turn(graph, "t-ac05", "status of CLM300210", AGENT, callbacks=[recorder])
    assert recorder.calls == []
    assert result.verification_passed is True
    assert "CLM300210" in result.answer_markdown and result.citations == ["[claims:CLM300210]"]


@pytest.mark.parametrize("text", ["Hello", "Thanks!"])
def test_AC_06_27_greeting_answered_from_template_without_llm(
    graph: Any, monkeypatch: pytest.MonkeyPatch, text: str
) -> None:
    forbid_llm(monkeypatch)
    recorder = LLMCallRecorder()
    result = run_turn(graph, f"t-ac27-{text}", text, "customer", principal_id=OWNER, callbacks=[recorder])
    assert recorder.calls == []
    assert result.answer_markdown == template("greeting")
    assert not any(e.kind == "llm" for e in result.trace)
    total = next(e for e in result.trace if e.kind == "total")
    assert total.data == {"answered_by": "template", "llm_written": False}


def test_AC_06_08_unknown_claim_not_found_no_invented_numbers(
    graph: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    forbid_llm(monkeypatch)
    result = run_turn(graph, "t-ac08", "Status of CLM999999", AGENT)
    assert result.answer_markdown == "I couldn't find claim CLM999999 in our records. Please check the ID."
    assert result.verification_passed is True
    assert number_tokens(result.answer_markdown) == {"CLM999999"}


def test_AC_06_07_agent_interrupt_resume_states_decision_and_note(
    graph: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_scripts(monkeypatch)
    paused = run_turn(graph, "t-ac07", "Analyze claim CLM300210", AGENT)
    assert paused.interrupt is not None and paused.interrupt["claim_id"] == "CLM300210"
    assert paused.interrupt["needs_human_review"] is True and paused.answer_markdown == ""

    done = resume(graph, "t-ac07", ReviewDecision(action="approve", note=NOTE))
    assert done.interrupt is None
    assert "Reviewer decision: **approve**" in done.answer_markdown and NOTE in done.answer_markdown
    assert done.assessment is not None and done.assessment["review"]["action"] == "approve"


def test_AC_06_07_customer_no_interrupt_specialist_review(
    graph: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_scripts(monkeypatch)
    result = run_turn(graph, "t-ac07c", "Analyze claim CLM300210", "customer", principal_id=OWNER)
    assert result.interrupt is None
    assert "A claims specialist will review this claim before a decision." in result.answer_markdown
    assert "Reviewer decision" not in result.answer_markdown


def test_run_turn_raises_review_pending_on_interrupted_thread(
    graph: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_scripts(monkeypatch)
    run_turn(graph, "t-pending", "Analyze claim CLM300210", AGENT)
    with pytest.raises(ReviewPending) as info:
        run_turn(graph, "t-pending", "which documents are missing?", AGENT)
    assert info.value.summary["claim_id"] == "CLM300210"
    resume(graph, "t-pending", ReviewDecision(action="request_info", note="Need discharge summary"))
    with pytest.raises(NoPendingReview):
        resume(graph, "t-pending", ReviewDecision(action="approve"))


def test_AC_06_04_followup_resolves_active_claim(graph: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_scripts(monkeypatch)
    run_turn(graph, "t-ac04", "Analyze CLM300210", AGENT)  # spec wording
    resume(graph, "t-ac04", ReviewDecision(action="approve", note="ok"))
    turn2 = run_turn(graph, "t-ac04", "which documents are missing?", AGENT)
    plan = next(e for e in turn2.trace if e.kind == "intent" and e.name == "plan")
    assert plan.data["intents"][0]["entities"]["claim_id"] == "CLM300210"
    tool = next(e for e in turn2.trace if e.kind == "tool")
    assert tool.name == "get_claim_documents" and tool.data["args"] == {"claim_id": "CLM300210"}
    assert "[claim_documents:CLM300210]" in turn2.answer_markdown


def test_AC_06_11_turn2_has_only_turn2_evidence_and_trace(
    graph: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    forbid_llm(monkeypatch)
    run_turn(graph, "t-ac11", "status of CLM300210", AGENT)
    turn2 = run_turn(graph, "t-ac11", "status of CLM300500", AGENT)
    values = graph.get_state({"configurable": {"thread_id": "t-ac11"}}).values
    labels = {s.label for ev in values["evidence"] for s in ev.sources}
    assert "[claims:CLM300500]" in labels and "[claims:CLM300210]" not in labels
    assert {e.turn for e in turn2.trace} == {2}
    stale = values["draft"].model_copy(update={"answer_markdown": "Approved. [claims:CLM300210]"})
    assert not verify(stale, values["evidence"], AGENT, "status of CLM300500").checks[0].passed


def test_AC_06_12_history_window_caps_prompts_at_6_turns(graph: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    for n in range(10):  # 10 prior turns on the fast path (no LLM), the last one sets the active claim
        run_turn(graph, "t-ac12", f"status of CLM30{n}210" if n < 9 else "status of CLM300210", AGENT)
    _install_scripts(monkeypatch)
    recorder = LLMCallRecorder()
    result = run_turn(graph, "t-ac12", "what contacts were there?", AGENT, callbacks=[recorder])
    planner_calls, synth_calls = recorder.tagged("prompt:planner"), recorder.tagged("prompt:synthesize")
    assert planner_calls and synth_calls
    for call in planner_calls + synth_calls:
        assert history_turns(call.message_types) == 6
    assert "[interactions:CLM300210]" in result.answer_markdown


def test_AC_06_09_trace_fields_on_fast_path(graph: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    forbid_llm(monkeypatch)
    trace = run_turn(graph, "t-ac09a", "status of CLM300210", AGENT).trace
    kinds = {e.kind for e in trace}
    assert {"node", "entity", "intent", "tool", "verify", "total"} <= kinds
    tool = next(e for e in trace if e.kind == "tool")
    assert {"args", "result_size", "result_kind"} <= set(tool.data) and tool.duration_ms >= 0
    assert next(e for e in trace if e.kind == "verify").data["checks"]


@pytest.mark.parametrize("question", ["status of CLM300210", "Hello"])
def test_AC_10_17_fast_path_intent_event_has_the_planner_row_shape(
    graph: Any, monkeypatch: pytest.MonkeyPatch, question: str
) -> None:
    """The UI trace reads {"id", "type", "entities"} rows; the fast paths must write the planner's shape."""
    forbid_llm(monkeypatch)
    trace = run_turn(graph, f"t-ac17-{question[:5]}", question, AGENT).trace
    rows = next(e for e in trace if e.kind == "intent").data["intents"]
    assert rows and all(isinstance(r, dict) and {"id", "type", "entities"} <= set(r) for r in rows)


@pytest.mark.usefixtures("index_path")
def test_AC_06_03_two_intents_overlapping_worker_spans(graph: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    question = "Status of CLM300500 and is drunk driving covered under Motor Protect Comprehensive?"
    two = plan_of(
        ("claim_status", {"claim_id": "CLM300500"}),
        ("policy_question", {"product": "Motor Protect Comprehensive"}),
        question="Is drunk driving covered under Motor Protect Comprehensive?",
    )
    install(monkeypatch, {"Plan": [two], "Text": citing_synth})
    result = run_turn(graph, "t-ac03", question, AGENT)
    plan = next(e for e in result.trace if e.kind == "intent" and e.name == "plan")
    assert [i["type"] for i in plan.data["intents"]] == ["claim_status", "policy_question"]
    spans = {e.name: e for e in result.trace if e.kind == "node" and e.name in ("claim_tools", "policy_rag")}
    a, b = spans["claim_tools"], spans["policy_rag"]
    assert a.start_ms < b.end_ms and b.start_ms < a.end_ms, "worker spans do not overlap"

    # AC-06-09 on the LLM path: retrieval chunk fields, prompt ids, token counts on every LLM call.
    retrieval = next(e for e in result.trace if e.kind == "retrieval")
    assert {"label", "fused_rank", "rerank_score", "via"} <= set(retrieval.data["chunks"][0])
    llm = [e for e in result.trace if e.kind == "llm"]
    # settings.yaml profile api-lite: guardrails.v7_live is on, so the V7 judge runs on the policy answer
    assert {e.name for e in llm} == {"planner", "synthesize", "verify_groundedness"}
    for e in llm:
        assert e.data["input_tokens"] and e.data["output_tokens"] and e.data["model"] and e.data["role"]
    assert {(e.data["prompt_id"], e.data["version"]) for e in result.trace if e.kind == "prompt"} == {
        (p.id, p.version)
        for p in (load_prompt("planner"), load_prompt("synthesize"), load_prompt("verify_groundedness"))
    }
    assert next(e for e in result.trace if e.kind == "total").duration_ms > 0


def test_verify_retries_once_with_feedback_then_abstains(graph: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    prompts: list[str] = []

    def bad_synth(messages: list[Any]) -> str:
        prompts.append(str(messages[0].content))
        return "Payable is ₹99,999. [claims:CLM300210]"  # invented number

    plan = plan_of(("claim_interactions", {"claim_id": "CLM300210"}), question="Who contacted us?")
    install(monkeypatch, {"Plan": [plan], "Text": bad_synth})
    result = run_turn(graph, "t-retry", "Who contacted us about CLM300210?", AGENT)
    outcomes = [e.data["outcome"] for e in result.trace if e.kind == "verify"]
    assert outcomes == ["retry", "abstain"]
    assert len(prompts) == 2 and "99999" in prompts[1]  # verifier feedback reached the retry
    assert result.answer_markdown.startswith("The policy documents don't address this directly.")
    assert "[interactions:CLM300210]" in result.answer_markdown and "99,999" not in result.answer_markdown


@pytest.mark.parametrize(
    ("entities", "question"),
    [
        ({"hospital_id": "HOSP1257"}, "Is HOSP1257 a network hospital?"),
        ({"claim_id": "CLM300210"}, "Is the hospital on CLM300210 in network?"),
    ],
)
def test_hospital_check_by_id_and_via_claim(
    graph: Any, monkeypatch: pytest.MonkeyPatch, entities: dict[str, str], question: str
) -> None:
    install(
        monkeypatch,
        {"Plan": [plan_of(("hospital_check", entities), question=question)], "Text": citing_synth},
    )
    result = run_turn(graph, f"t-hosp-{len(entities)}-{question[:6]}", question, AGENT)
    assert [e.name for e in result.trace if e.kind == "tool"][-1] == "check_hospital"
    assert result.verification_passed is True


@pytest.mark.usefixtures("index_path")
def test_rule2_unanswerable_without_product_abstains_without_llm_synthesis(
    graph: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    question = "Are vet bills for my pet dog covered?"

    def no_synth(messages: list[Any]) -> Any:
        raise AssertionError("synthesizer must not run: the abstention is a template")

    install(monkeypatch, {"Plan": [plan_of(("policy_question", {}), question=question)], "Text": no_synth})
    result = run_turn(graph, "t-abstain", question, AGENT)
    assert result.answer_markdown.startswith("The policy documents don't address this directly.")
    assert result.verification_passed is True and result.citations


@pytest.mark.usefixtures("index_path")
def test_AC_06_06_real_probe_still_clarifies_waiting_period(
    graph: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    question = "what is the waiting period?"
    install(monkeypatch, {"Plan": [plan_of(("policy_question", {}), question=question)]})
    result = run_turn(graph, "t-ac06", question, AGENT)
    assert result.answer_markdown.startswith("Which product do you mean?")


async def _events(graph: Any, thread_id: str, message: str) -> list[tuple[str, Any]]:
    from insurai.agent.runner import astream_turn

    return [e async for e in astream_turn(graph, thread_id, message, AGENT)]


async def test_AC_06_14_fast_path_and_not_found_template_emit_no_tokens(
    graph: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    forbid_llm(monkeypatch)
    for n, message in enumerate(("status of CLM300210", "status of CLM999999")):
        events = await _events(graph, f"t-ac14-{n}", message)
        names = [name for name, _ in events]
        assert "token" not in names and "draft_hidden" not in names and names[-1] == "result"


async def test_AC_06_14_planner_not_found_template_emits_no_tokens(
    graph: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_synth(messages: list[Any]) -> Any:
        raise AssertionError("NOT_FOUND is a template; no synthesis")

    plan = plan_of(("claim_documents", {"claim_id": "CLM999999"}), question="Which documents are missing?")
    install(monkeypatch, {"Plan": [plan], "Text": no_synth})
    events = await _events(graph, "t-ac14-nf", "Which documents are missing for CLM999999?")
    assert "token" not in [name for name, _ in events]


async def test_AC_06_13_verify_runs_on_the_full_streamed_text(
    graph: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = "The claim's contacts are listed in the record. [interactions:CLM300210] Payable is ₹99,999."
    plan = plan_of(("claim_interactions", {"claim_id": "CLM300210"}), question="Who contacted us?")
    install(monkeypatch, {"Plan": [plan], "Text": lambda messages: text})
    events = await _events(graph, "t-ac13-full", "Who contacted us about CLM300210?")
    first = [d["text"] for name, d in events if name == "token" and d["attempt"] == 1]
    assert "".join(first) == text and "99,999" in first[-1]  # the orphan number arrives in the last chunk
    outcomes = [d.get("outcome") for name, d in events if name == "node" and d["name"] == "verify"]
    outcomes = [o for o in outcomes if o]
    assert outcomes == ["retry", "abstain"]  # V3 saw the complete text, not a prefix
    result = events[-1][1]
    assert "99,999" not in result.answer_markdown


# --- template answers (spec 06, AC-06-21, AC-06-22) -----------------------------------------------------

TEMPLATE_CASES = [
    # (intent, entities, question, owner of the claim or policy, expected text)
    ("claim_status", {"claim_id": "CLM300210"}, "Has CLM300210 been settled?", OWNER, "**Approved**"),
    (
        "claim_documents",
        {"claim_id": "CLM418078"},
        "What paperwork is still needed for CLM418078?",
        "CUST127701",
        "No documents are missing for claim CLM418078.",
    ),
    (
        "hospital_check",
        {"claim_id": "CLM300210"},
        "Is the hospital on CLM300210 in network?",
        OWNER,
        "The hospital on claim CLM300210 is",
    ),
    (
        "hospital_check",
        {"claim_id": "CLM363235"},
        "Is the hospital on CLM363235 in network?",
        OWNER,
        "Network alternatives in",
    ),
    (
        "policy_details",
        {"policy_id": "POL218917"},
        "What is the sum insured on POL218917?",
        OWNER,
        "Policy POL218917",
    ),
    (
        "policy_details",
        {"claim_id": "CLM300210"},
        "Which policy schedule applies to CLM300210?",
        OWNER,
        "Claim CLM300210 is on policy POL218917",
    ),
]


def _no_synth(messages: list[Any]) -> Any:
    raise AssertionError("a single SQL-fact intent is a template answer; no synthesis")


@pytest.mark.parametrize("persona", [AGENT, "customer"])
@pytest.mark.parametrize(("intent", "entities", "question", "owner", "expected"), TEMPLATE_CASES)
def test_AC_06_21_single_sql_fact_turn_is_a_cited_template_answer(
    graph: Any,
    monkeypatch: pytest.MonkeyPatch,
    persona: str,
    intent: str,
    entities: dict[str, str],
    question: str,
    owner: str,
    expected: str,
) -> None:
    from insurai.agent.answers import TEMPLATE_INTENTS
    from insurai.settings import get_settings
    from insurai.tools.registry import TOOLS
    from insurai.tools.schemas import ToolContext

    assert intent in TEMPLATE_INTENTS
    install(monkeypatch, {"Plan": [plan_of((intent, entities), question=question)], "Text": _no_synth})
    recorder = LLMCallRecorder()
    principal = owner if persona == "customer" else None
    thread = f"t-tpl-{persona}-{intent}-{next(iter(entities.values()))}"
    result = run_turn(graph, thread, question, persona, principal, callbacks=[recorder])
    assert recorder.tagged("prompt:synthesize") == []
    assert result.verification_passed is True
    assert expected in result.answer_markdown and result.citations
    assert "None" not in result.answer_markdown
    if persona == "customer":  # hidden fields never reach a customer answer
        claim_id = entities.get("claim_id", "CLM300210")
        agent_ctx = ToolContext(
            persona=AGENT, principal_id=None, as_of=get_settings().as_of_date, trace_id="t"
        )
        name = TOOLS["get_claim"](agent_ctx, claim_id).customer_name
        assert name and name not in result.answer_markdown


def test_AC_06_21_mixed_plan_still_synthesizes(graph: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = plan_of(
        ("claim_status", {"claim_id": "CLM300210"}), ("claim_interactions", {"claim_id": "CLM300210"})
    )
    install(monkeypatch, {"Plan": [plan], "Text": citing_synth})
    recorder = LLMCallRecorder()
    run_turn(graph, "t-tpl-mixed", "Status of CLM300210 and any contacts?", AGENT, callbacks=[recorder])
    assert recorder.tagged("prompt:synthesize")


def test_AC_06_22_false_premise_on_a_claim_status_turn_is_corrected(
    graph: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = plan_of(("claim_status", {"claim_id": "CLM300210"}), question="Is CLM300210 pending?")
    install(monkeypatch, {"Plan": [plan], "Text": _no_synth})
    result = run_turn(graph, "t-premise-status", "Is CLM300210 pending?", AGENT)
    assert result.answer_markdown.startswith("CLM300210 is Approved, not pending [claims:CLM300210].")
    assert result.verification_passed is True
