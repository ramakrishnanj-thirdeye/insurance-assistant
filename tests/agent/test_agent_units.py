"""Unit tests for the agent graph pieces: no warehouse, no index, no LLM."""

from typing import Any

import pytest
from fakes import plan_of
from langchain_core.messages import AIMessage, HumanMessage

from insurai.agent.graph import MERMAID_FILE, NODES, build_graph, input_guard, mermaid
from insurai.agent.history import window
from insurai.agent.planner import PlanContext, finalize_plan
from insurai.agent.resolve import is_fast_path, is_follow_up, match_product, resolve_entities
from insurai.agent.schemas import AnswerDraft, Entities, Evidence, Plan, Reset, TraceEvent
from insurai.agent.state import merge_evidence, merge_trace
from insurai.agent.trace import llm_events
from insurai.guardrails.verify import verify
from insurai.llm.structured import LLMCall
from insurai.tools.schemas import SourceRef

pytestmark = pytest.mark.unit


def _ev(label: str, intent_id: str = "i1") -> Evidence:
    return Evidence(
        intent_id=intent_id,
        worker="claim_tools",
        kind="ClaimView",
        payload={},
        sources=[SourceRef(kind="sql", label=label)],
        summary="",
    )


def _ctx(**overrides: Any) -> PlanContext:
    base: dict[str, Any] = {
        "persona": "claims_agent",
        "principal_id": None,
        "message": "q",
        "resolved": Entities(),
        "active": Entities(),
        "max_intents": 4,
    }
    return PlanContext(**(base | overrides))


# --- AC-06-01 ----------------------------------------------------------------------------------------------


def test_AC_06_01_graph_compiles_mermaid_matches_node_table() -> None:
    drawn = build_graph().get_graph()
    assert set(drawn.nodes) - {"__start__", "__end__"} == set(NODES)
    assert MERMAID_FILE.read_text(encoding="utf-8") == mermaid()


# --- per-turn reset (AC-06-11 building blocks) -------------------------------------------------------------


def test_merge_evidence_reset() -> None:
    assert merge_evidence([_ev("[claims:CLM1]")], Reset()) == []
    assert len(merge_evidence([_ev("[claims:CLM1]")], [_ev("[claims:CLM2]")])) == 2
    t = TraceEvent(kind="node", name="x", turn=1, start_ms=0, end_ms=1)
    assert merge_trace([t], Reset()) == []


def test_input_guard_resets_per_turn() -> None:
    state: Any = {
        "messages": [HumanMessage("status of CLM300210", id="m1")],
        "persona": "claims_agent",
        "turn": 3,
        "evidence": [_ev("[claims:CLM300210]")],
        "attempts": 1,
        "plan": plan_of(("claim_status", {})),
        "active_entities": Entities(claim_id="CLM300210"),
    }
    update = input_guard(state)
    assert isinstance(update["evidence"], Reset)
    assert update["turn"] == 4 and update["attempts"] == 0
    for key in ("plan", "assessment", "review", "draft", "verification"):
        assert update[key] is None
    assert "active_entities" not in update  # carried across turns
    assert isinstance(update["trace"], Reset)  # the guard span is traced by the next node


def test_input_guard_masks_pii_in_the_stored_message() -> None:
    state: Any = {
        "messages": [HumanMessage("my phone 9876543210, CLM300210 status", id="m1")],
        "persona": "customer",
        "principal_id": "CUST139920",
    }
    update = input_guard(state)
    assert update["messages"][0].id == "m1" and "9876543210" not in update["messages"][0].content
    assert update["active_entities"] == Entities(customer_id="CUST139920")


def test_AC_06_11_turn1_label_fails_v1() -> None:
    turn2 = [_ev("[claims:CLM300500]")]
    draft = AnswerDraft(answer_markdown="Approved. [claims:CLM300210]")
    report = verify(draft, turn2, "claims_agent", "and the other claim?")
    assert not report.checks[0].passed and report.invalid_citations == ["[claims:CLM300210]"]


# --- resolve_context ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "fast"),
    [
        ("status of CLM300210", True),
        ("What is the status of claim CLM383810?", True),
        ("where is CLM300210", True),
        ("Status of CLM300500 and is drunk driving covered under Motor Protect Comprehensive?", False),
        ("status of CLM300210 and CLM300500", False),
        ("Which documents are missing for CLM300210 status?", False),
        ("Why is the status of CLM300210 still pending?", False),
        ("How much was approved on claim CLM300210?", False),
        ("Analyze claim CLM300210", False),
    ],
)
def test_fast_path_rule(text: str, fast: bool) -> None:
    assert is_fast_path(text) is fast


def test_gazetteer_aliases_and_fuzzy() -> None:
    assert match_product("is drunk driving covered under MPC?") == "Motor Protect Comprehensive"
    assert match_product("waiting period in Helth Secure Plus") == "Health Secure Plus"
    assert match_product("what is the waiting period?") is None


def test_resolve_entities_and_follow_ups() -> None:
    e = resolve_entities("Is HOSP1257 on POL218917 for CLM300210 under Two Wheeler Secure?")
    assert e == Entities(
        claim_id="CLM300210", policy_id="POL218917", hospital_id="HOSP1257", product="Two Wheeler Secure"
    )
    assert is_follow_up("which documents are missing for it?")
    assert not is_follow_up("Is dental covered?")


# --- planner finalisation ----------------------------------------------------------------------------------


def test_AC_06_06_agent_no_context_waiting_period_clarifies() -> None:
    plan = plan_of(("policy_question", {}), question="What is the waiting period?")
    final = finalize_plan(plan, _ctx(message="what is the waiting period?"))
    assert not final.intents and final.clarification and final.clarification.startswith("Which product")


def test_generic_question_runs_unfiltered_without_clarification() -> None:
    plan = plan_of(("policy_question", {}), question="Can approval be guaranteed?")
    final = finalize_plan(plan, _ctx(product_probe=lambda q: "common"))
    assert final.clarification is None and final.intents[0].entities.product is None


def test_product_from_active_then_customer_single_product() -> None:
    plan = plan_of(("policy_question", {}))
    assert finalize_plan(plan, _ctx(active=Entities(product="Family Care Gold"))).intents[
        0
    ].entities.product == ("Family Care Gold")
    final = finalize_plan(
        plan, _ctx(persona="customer", principal_id="CUST1", own_products=lambda: ["Maternity Protect"])
    )
    assert final.intents[0].entities.product == "Maternity Protect"
    several = finalize_plan(
        plan, _ctx(persona="customer", own_products=lambda: ["Car Shield Plus", "Family Care Gold"])
    )
    assert several.clarification == "Which product do you mean? Car Shield Plus, Family Care Gold"


def test_follow_up_fills_claim_and_drops_invented_ids() -> None:
    plan = plan_of(("claim_documents", {"claim_id": "CLM123456"}))  # not in message or context
    final = finalize_plan(
        plan, _ctx(message="which documents are missing?", active=Entities(claim_id="CLM300210"))
    )
    assert final.intents[0].entities.claim_id == "CLM300210"


def test_more_than_four_intents_are_capped_with_a_note() -> None:
    intents = [("claim_status", {"claim_id": "CLM300210"})] * 5
    ctx = _ctx(message="CLM300210", resolved=Entities(claim_id="CLM300210"))
    final = finalize_plan(plan_of(*intents), ctx)
    assert len(final.intents) == 4 and [i.id for i in final.intents] == ["i1", "i2", "i3", "i4"]
    assert ctx.notes == ["You asked about 5 things; I answered the first 4. Ask again for the rest."]


def test_claim_intent_without_any_claim_asks_which_claim() -> None:
    final = finalize_plan(
        plan_of(("claim_status", {})), _ctx(persona="customer", own_claims=lambda: ["CLM1", "CLM2"])
    )
    assert final.clarification == "Which claim do you mean? CLM1, CLM2"


def test_clarification_plan_passes_through() -> None:
    plan = Plan(clarification="Which product do you mean?")
    assert finalize_plan(plan, _ctx()) == plan


# --- history window, trace -------------------------------------------------------------------------------


def test_history_window_keeps_last_six_turns_excluding_current() -> None:
    msgs: list[Any] = []
    for i in range(10):
        msgs += [HumanMessage(f"q{i}"), AIMessage(f"a{i}")]
    msgs.append(HumanMessage("now"))
    kept = window(msgs, 6)
    assert len(kept) == 12 and kept[0].content == "q4" and kept[-1].content == "a9"


def test_llm_events_add_warning_when_ctx_near_limit() -> None:
    call = LLMCall(
        role="generator",
        model="qwen3:8b",
        prompt_id="planner",
        prompt_version="0.2.0",
        input_tokens=7500,
        output_tokens=40,
        latency_ms=12.0,
        attempts=1,
        ctx_warning={"input_tokens": 7500, "num_ctx": 8192, "model": "qwen3:8b"},
    )
    events = llm_events(call, turn=2, start_ms=0)
    assert [e.kind for e in events] == ["llm", "prompt", "warning"]
    assert events[0].data["input_tokens"] == 7500 and events[2].data["num_ctx"] == 8192
    assert [e.kind for e in llm_events(call.model_copy(update={"ctx_warning": None}), 2, 0)] == [
        "llm",
        "prompt",
    ]


@pytest.mark.parametrize("claim_intent", ["claim_documents", "claim_analysis"])
def test_claim_intent_without_claim_but_with_product_becomes_policy_question(claim_intent: str) -> None:
    question = "Under Family Care Gold, what documents must I submit for a reimbursement claim?"
    plan = plan_of((claim_intent, {"product": "Family Care Gold"}), question=question)
    final = finalize_plan(plan, _ctx(message=question, resolved=Entities(product="Family Care Gold")))
    assert final.clarification is None
    assert [(i.type, i.entities.product) for i in final.intents] == [("policy_question", "Family Care Gold")]


def test_claim_intent_with_active_claim_stays_a_claim_intent() -> None:
    plan = plan_of(("claim_analysis", {}), question="Can you guarantee my claim will be approved?")
    final = finalize_plan(plan, _ctx(active=Entities(claim_id="CLM300210", product="Critical Care Elite")))
    assert final.intents[0].type == "claim_analysis" and final.intents[0].entities.claim_id == "CLM300210"


def test_rule2_no_confident_hit_anywhere_skips_the_product_clarification() -> None:
    plan = plan_of(("policy_question", {}), question="Are vet bills for my pet covered?")
    final = finalize_plan(plan, _ctx(product_probe=lambda q: "none"))
    assert final.clarification is None
    assert [(i.type, i.entities.product) for i in final.intents] == [("policy_question", None)]


def test_rule2_confident_product_specific_hit_still_asks_for_the_product() -> None:
    plan = plan_of(("policy_question", {}), question="What is the waiting period?")
    final = finalize_plan(plan, _ctx(product_probe=lambda q: "product"))
    assert final.clarification is not None and final.clarification.startswith("Which product")


def test_policy_details_without_policy_but_with_product_becomes_policy_question() -> None:
    question = "Is there a deductible under Family Care Gold?"
    plan = plan_of(("policy_details", {"product": "Family Care Gold"}), question=question)
    final = finalize_plan(plan, _ctx(message=question, resolved=Entities(product="Family Care Gold")))
    assert [(i.type, i.entities.product) for i in final.intents] == [("policy_question", "Family Care Gold")]
    no_product = finalize_plan(plan_of(("policy_details", {})), _ctx())
    assert no_product.clarification == "Which policy do you mean? Give the policy ID (like POL100001)."


# --- claim analysis: explain vs assess, narrative as the answer (specs 06, 07) ---------------------------


@pytest.mark.parametrize(
    ("message", "mode"),
    [("Analyze claim CLM300210", "assess"), ("Why is CLM300210 pending?", "explain")],
)
def test_finalize_plan_sets_mode_and_question_on_claim_analysis(message: str, mode: str) -> None:
    plan = plan_of(
        ("claim_analysis", {"claim_id": "CLM300210"}), ("claim_documents", {"claim_id": "CLM300210"})
    )
    final = finalize_plan(plan, _ctx(message=message))
    analysis, docs = final.intents
    assert (analysis.mode, analysis.question) == (mode, message)
    assert (docs.mode, docs.question) == (None, None)


def test_planner_schema_hides_mode_and_question() -> None:
    properties = Plan.model_json_schema()["$defs"]["Intent"]["properties"]
    assert "mode" not in properties and "question" not in properties


def test_narrative_is_answer_only_for_claim_analysis_turns() -> None:
    from insurai.agent.synthesize import narrative_is_answer

    same = plan_of(
        ("claim_analysis", {"claim_id": "CLM300210"}), ("claim_documents", {"claim_id": "CLM300210"})
    )
    other_claim = plan_of(
        ("claim_analysis", {"claim_id": "CLM300210"}), ("claim_status", {"claim_id": "CLM300500"})
    )
    mixed = plan_of(
        ("claim_analysis", {"claim_id": "CLM300210"}), ("policy_question", {"product": "Health Secure Plus"})
    )
    assert narrative_is_answer(plan_of(("claim_analysis", {"claim_id": "CLM300210"})))
    assert narrative_is_answer(same)
    assert not narrative_is_answer(other_claim) and not narrative_is_answer(mixed)
    assert not narrative_is_answer(
        plan_of(("claim_status", {"claim_id": "CLM300210"}))
    ) and not narrative_is_answer(None)


# --- verify: the M4 root cause and the dossier narrative --------------------------------------------------


def test_evidence_block_ids_are_not_cited_v1_flags_them() -> None:
    """M4 manual test: the generator cited [e2] (an evidence block id) instead of the source label, so the
    post-override answer failed V2 twice. Blocks carry no ids now, and V1 names such pseudo-labels."""
    from insurai.agent.synthesize import evidence_blocks

    evidence = [_ev("[claims:CLM300210]")]
    assert 'id="e' not in evidence_blocks(evidence)
    report = verify(
        AnswerDraft(answer_markdown="Claim CLM300210 is Approved [e1]."), evidence, "claims_agent", "q"
    )
    v1 = next(c for c in report.checks if c.check == "V1")
    assert not v1.passed and "[e1]" in v1.detail and "not citations" in report.feedback


def test_model_written_narrative_is_not_a_number_source() -> None:
    ev = _ev("[claims:CLM300210]").model_copy(update={"payload": {"narrative": "Payable ₹12,34,567."}})
    report = verify(
        AnswerDraft(answer_markdown="Payable ₹12,34,567. [claims:CLM300210]"), [ev], "claims_agent", "q"
    )
    assert report.orphan_numbers == ["1234567"]


def test_rewrite_guarantees_keeps_lines_and_lists() -> None:
    from insurai.guardrails.verify import rewrite_guarantees

    text = "Position line.\n- This claim will definitely be approved. Other point.\n- Second item."
    out = rewrite_guarantees(text)
    assert out.split("\n")[0] == "Position line." and out.count("\n") == 2
    assert "definitely" not in out and "Final decision depends on complete claim assessment." in out
