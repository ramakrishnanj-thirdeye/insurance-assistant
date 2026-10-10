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
    message = "What's happening with my claim?"
    final = finalize_plan(
        plan_of(("claim_status", {}), question=message),
        _ctx(persona="customer", message=message, own_claims=lambda: ["CLM1", "CLM2"]),
    )
    assert final.clarification == "Which claim do you mean? CLM1, CLM2"


# --- AC-06-23 / AC-06-24 -----------------------------------------------------------------------------------


@pytest.mark.parametrize("claim_intent", ["claim_status", "claim_analysis", "claim_documents"])
def test_AC_06_23_claim_intent_without_any_claim_reference_is_a_policy_question(claim_intent: str) -> None:
    message = "Does a pre-authorisation at a network hospital mean the bill is already paid?"
    plan = plan_of((claim_intent, {}), question=message)
    final = finalize_plan(plan, _ctx(message=message, product_probe=lambda q: "common"))
    assert final.clarification is None
    assert [(i.type, i.entities.product) for i in final.intents] == [("policy_question", None)]


@pytest.mark.parametrize(
    "message",
    ["Has my claim been settled?", "Where is the claim number I was sent?", "Any news on CLM300210?"],
)
def test_AC_06_23_claim_reference_still_asks_which_claim(message: str) -> None:
    final = finalize_plan(plan_of(("claim_status", {}), question=message), _ctx(message=message))
    assert final.clarification is not None and final.clarification.startswith("Which claim")


def test_AC_06_24_invented_product_is_dropped_before_rule_2() -> None:
    message = "Is treatment for my cat's injury covered?"
    plan = plan_of(("policy_question", {"product": "Maternity Protect"}), question=message)
    final = finalize_plan(plan, _ctx(message=message, product_probe=lambda q: "none"))
    assert final.clarification is None
    assert [(i.type, i.entities.product) for i in final.intents] == [("policy_question", None)]


def test_AC_06_24_product_named_in_message_or_context_is_kept() -> None:
    message = "Is dental treatment covered under the family care plan?"
    named = finalize_plan(
        plan_of(("policy_question", {"product": "Family Care Gold"}), question=message), _ctx(message=message)
    )
    assert named.intents[0].entities.product == "Family Care Gold"
    follow_up = finalize_plan(
        plan_of(("policy_question", {"product": "Car Shield Plus"}), question="Is it covered?"),
        _ctx(message="Is it covered?", active=Entities(product="Car Shield Plus")),
    )
    assert follow_up.intents[0].entities.product == "Car Shield Plus"
    via_claim = finalize_plan(
        plan_of(("policy_question", {"product": "Critical Care Elite"}), question="Is CLM300210 covered?"),
        _ctx(
            message="Is CLM300210 covered?",
            resolved=Entities(claim_id="CLM300210"),
            product_of=lambda e: "Critical Care Elite" if e.claim_id == "CLM300210" else None,
        ),
    )
    assert via_claim.intents[0].entities.product == "Critical Care Elite"


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
    [
        ("Analyze claim CLM300210 and its missing documents", "assess"),
        ("Why is CLM300210 pending?", "explain"),
    ],
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


# --- deterministic routing: pruning and promotion (spec 06 rules 9 and 10) --------------------------------


def _types(plan: Plan) -> list[str]:
    return [i.type for i in plan.intents]


def test_AC_06_19_stray_claim_documents_on_a_hospital_question_is_pruned() -> None:
    plan = plan_of(
        ("claim_documents", {"claim_id": "CLM300210"}), ("hospital_check", {"claim_id": "CLM300210"})
    )
    ctx = _ctx(message="Is the hospital on CLM300210 empanelled?", resolved=Entities(claim_id="CLM300210"))
    final = finalize_plan(plan, ctx)
    assert _types(final) == ["hospital_check"] and final.intents[0].id == "i1"
    assert ctx.pruned == ["claim_documents"]


def test_AC_06_19_stray_claim_analysis_next_to_a_policy_question_is_pruned() -> None:
    plan = plan_of(
        ("claim_analysis", {"claim_id": "CLM300210"}), ("policy_question", {"product": "Two Wheeler Secure"})
    )
    message = "Does this claim's policy pay for riding after drinking?"
    ctx = _ctx(
        message=message, active=Entities(claim_id="CLM300210"), product_of=lambda e: "Two Wheeler Secure"
    )
    final = finalize_plan(plan, ctx)
    assert _types(final) == ["policy_question"]


def test_AC_06_19_single_intent_is_never_pruned_and_an_all_pruned_plan_is_kept() -> None:
    single = finalize_plan(plan_of(("claim_documents", {"claim_id": "CLM300210"})), _ctx(message="CLM300210"))
    both = plan_of(
        ("claim_documents", {"claim_id": "CLM300210"}), ("hospital_check", {"claim_id": "CLM300210"})
    )
    ctx = _ctx(message="CLM300210 please")
    kept = finalize_plan(both, ctx)
    assert _types(single) == ["claim_documents"]
    assert _types(kept) == ["claim_documents", "hospital_check"] and ctx.pruned == []


def test_AC_06_19_unlisted_intents_are_never_pruned() -> None:
    plan = plan_of(
        ("policy_question", {"product": "Car Shield Plus"}), ("hospital_check", {"hospital_id": "HOSP1"})
    )
    final = finalize_plan(plan, _ctx(message="Is HOSP1 in network, and what does my car shield cover?"))
    assert _types(final) == ["policy_question", "hospital_check"]


def test_AC_06_19_triggers_come_from_definitions_config_and_glossary() -> None:
    from insurai.agent.routing import routing_config

    triggers = routing_config().triggers
    assert "Discharge Summary" in triggers["claim_documents"]  # config/required_documents.yaml
    assert "adjudicate" in triggers["claim_analysis"]  # config/rules.yaml dossier.assess_keywords
    assert "under review" in triggers["claim_status"]  # config/rules.yaml dossier.status_words
    assert "copayment" in triggers["policy_details"]  # glossary group of co-pay
    assert "empanelled hospital" in triggers["hospital_check"]  # glossary group of network hospital
    assert "policy_question" not in triggers


def test_AC_06_19_golden_expected_intents_have_a_trigger_safety_net() -> None:
    """Safety net, not a tuning target: every expected intent of a multi-intent golden item must survive
    pruning. A failure means a general term is missing (log it in tasks.md), never an eval phrase."""
    import json

    from insurai.agent.routing import mentions, routing_config
    from insurai.settings import ROOT

    triggers = routing_config().triggers
    misses = []
    for path in sorted((ROOT / "eval" / "datasets").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            item = json.loads(line) if line.strip() else None
            if not item or len(item.get("expected_route", [])) < 2:
                continue
            last = [t["content"] for t in item["turns"] if t.get("role", "user") == "user"][-1]
            misses += [
                (item["id"], intent)
                for intent in item["expected_route"]
                if intent in triggers and not mentions(last, triggers[intent])
            ]
    assert not misses


@pytest.mark.parametrize(
    "message",
    [
        "Give me a summary of claim CLM300210",
        "Why is CLM300210 pending?",
        "Can I get an overview of CLM300210?",
        "Please summarise CLM300210",
        "summarize CLM300210 for me",
    ],
)
def test_AC_06_20_summary_and_why_questions_promote_claim_status_to_explain(message: str) -> None:
    ctx = _ctx(message=message, resolved=Entities(claim_id="CLM300210"))
    final = finalize_plan(plan_of(("claim_status", {"claim_id": "CLM300210"})), ctx)
    (intent,) = final.intents
    assert (intent.type, intent.mode, intent.question) == ("claim_analysis", "explain", message)
    assert ctx.promoted == 1


def test_AC_06_20_promoted_intent_explains_even_with_an_assess_word() -> None:
    message = "Why did you reject CLM300210?"  # "reject" is an assess keyword
    final = finalize_plan(plan_of(("claim_status", {"claim_id": "CLM300210"})), _ctx(message=message))
    assert final.intents[0].mode == "explain"


def test_AC_06_20_claim_status_on_an_analysed_claim_collapses_into_the_analysis() -> None:
    plan = plan_of(("claim_analysis", {"claim_id": "CLM300210"}), ("claim_status", {"claim_id": "CLM300210"}))
    final = finalize_plan(plan, _ctx(message="Analyze CLM300210 and give its status"))
    assert _types(final) == ["claim_analysis"] and final.intents[0].id == "i1"
    other = plan_of(
        ("claim_analysis", {"claim_id": "CLM300210"}), ("claim_status", {"claim_id": "CLM300500"})
    )
    message = "Analyze CLM300210; status of CLM300500"
    assert _types(finalize_plan(other, _ctx(message=message))) == ["claim_analysis", "claim_status"]


def test_AC_06_20_no_promotion_without_a_summary_or_why_word() -> None:
    final = finalize_plan(
        plan_of(("claim_status", {"claim_id": "CLM300210"})), _ctx(message="Is CLM300210 paid?")
    )
    assert _types(final) == ["claim_status"] and final.intents[0].mode is None
