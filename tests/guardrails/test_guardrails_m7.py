"""Spec 08 guardrails that land in M7: V5–V7, v7_live, guarantee requests, conflicts, log redaction."""

import logging
from datetime import date
from typing import Any

import pytest
from fakes import plan_of

from insurai.agent import guarantee
from insurai.agent.graph import verify_node
from insurai.agent.planner import PlanContext, finalize_plan
from insurai.agent.schemas import AnswerDraft, Entities, Evidence
from insurai.guardrails import leakage
from insurai.guardrails.conflicts import ensure_conflicts_rendered, find_conflicts, precedence_sentence
from insurai.guardrails.input import check_input
from insurai.guardrails.pii import redact_for_logs
from insurai.guardrails.schemas import GroundedClaim, GroundednessVerdict, HiddenValues
from insurai.guardrails.verify import verify
from insurai.observability import get_logger
from insurai.settings import get_settings, v7_live_now
from insurai.tools.schemas import SourceRef

pytestmark = pytest.mark.unit

AS_OF = date(2026, 10, 1)
CLAIM = "[claims:CLM300500]"
POLICY = "[policies:POL200025]"
HSP_S4 = "[Health Secure Plus §4 Waiting Period]"
S15 = "[All products §15 Training FAQ Q1]"
MANDATED = "Final decision depends on complete claim assessment."
RAW_PII = {"aadhaar": "2345 6789 0123", "pan": "ABCDE1234F", "phone": "9876543210"}


def _ev(payload: dict[str, Any], labels: list[str], kind: str = "ClaimView", **refs: Any) -> Evidence:
    sources = [
        SourceRef(kind="sql" if ":" in label else "policy", label=label, **refs.get(label, {}))
        for label in labels
    ]
    return Evidence(intent_id="i1", worker="w", kind=kind, payload=payload, sources=sources, summary="")


def _check(report: Any, check_id: str) -> Any:
    return next(c for c in report.checks if c.check == check_id)


def _retrieval(clauses: list[tuple[str, int, str]], **extra: Any) -> Evidence:
    """Retrieval evidence from (label, section_no, text) clauses."""
    return Evidence(
        intent_id="i2",
        worker="policy_rag",
        kind="RetrievalResult",
        payload={"clauses": [{"label": lb, "product": "ALL", "text": t} for lb, _, t in clauses], **extra},
        sources=[SourceRef(kind="policy", label=lb, section_no=no) for lb, no, _ in clauses],
        summary="",
    )


# --- V5 PII leakage ---------------------------------------------------------------------------------------


def test_AC_08_10_V5_fails_output_pii_not_in_evidence() -> None:
    ev = [_ev({"claim_status": "Approved"}, [CLAIM])]
    draft = AnswerDraft(answer_markdown=f"We will call you on 9876543210. {CLAIM}")
    report = verify(draft, ev, "claims_agent", "q", AS_OF)
    v5 = _check(report, "V5")
    assert not v5.passed and v5.detail == "PHONE_IN" and "9876543210" not in report.feedback


def test_AC_08_10_V5_passes_pii_present_in_evidence() -> None:
    ev = [_ev({"contact_phone": "98765-43210"}, [CLAIM])]
    draft = AnswerDraft(answer_markdown=f"The contact on record is 9876543210. {CLAIM}")
    assert _check(verify(draft, ev, "claims_agent", "q", AS_OF), "V5").passed


def test_AC_08_10_V5_customer_name_only_for_personas_that_may_see_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(leakage, "known_names", lambda: frozenset({"Meera Nair"}))
    ev = [_ev({"claim_status": "Approved"}, [CLAIM])]
    draft = AnswerDraft(answer_markdown=f"Meera Nair, your claim is Approved. {CLAIM}")
    customer = _check(verify(draft, ev, "customer", "q", AS_OF), "V5")
    assert not customer.passed and customer.detail == "1 customer name(s)" and "Meera" not in customer.detail
    assert _check(verify(draft, ev, "claims_agent", "q", AS_OF), "V5").passed


def test_AC_08_10_V5_names_from_evidence_count_without_the_warehouse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(leakage, "known_names", lambda: frozenset())
    ev = [_ev({"customer_name": "Arjun Sharma"}, [CLAIM])]
    draft = AnswerDraft(answer_markdown=f"Arjun Sharma filed it. {CLAIM}")
    assert not _check(verify(draft, ev, "customer", "q", AS_OF), "V5").passed


# --- V6 hidden fields -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sentence",
    [
        "Your fraud score is low.",
        "The fraud_risk_score is below threshold.",
        "Your claim has a manual review flag.",
        "The claim is flagged for manual review.",
        "Your risk segment is on file.",
        "You are a high-risk customer.",
        "You are a Medium risk.",
        "Your risk category is standard.",
    ],
)
def test_AC_08_11_V6_fails_each_hidden_term_for_customers(sentence: str) -> None:
    ev = [_ev({"claim_status": "Approved"}, [CLAIM])]
    report = verify(AnswerDraft(answer_markdown=f"{sentence} {CLAIM}"), ev, "customer", "q", AS_OF)
    assert not _check(report, "V6").passed and "fraud scores" in report.feedback


@pytest.mark.parametrize(
    ("answer", "hit"),
    [
        ("Your claim scored 0.218 on our checks.", "fraud score value"),
        ("Your score was 0.22.", "fraud score value"),
        ("Your segment: High.", "risk segment value"),
        ("risk: High", "risk segment value"),
        ("You sit in the High band.", "risk segment value"),
    ],
)
def test_AC_08_11_V6_fails_the_hidden_values_themselves(answer: str, hit: str) -> None:
    hidden = HiddenValues(fraud_scores={"0.218", "0.22"}, segments={"High"})
    ev = [_ev({"claim_status": "Approved"}, [CLAIM])]
    v6 = _check(
        verify(AnswerDraft(answer_markdown=f"{answer} {CLAIM}"), ev, "customer", "q", AS_OF, hidden=hidden),
        "V6",
    )
    assert not v6.passed and hit in v6.detail


def test_AC_08_11_V6_passes_benign_customer_wording_and_ignores_staff() -> None:
    hidden = HiddenValues(fraud_scores={"0.218"}, segments={"High"})
    ev = [_ev({"claim_status": "Approved"}, [CLAIM])]
    benign = AnswerDraft(
        answer_markdown=f"High-risk adventure activities are excluded, and complex claims may be escalated "
        f"for manual review. The claim is Approved, with a High priority on our side. {CLAIM}"
    )
    assert _check(verify(benign, ev, "customer", "q", AS_OF, hidden=hidden), "V6").passed
    staff = AnswerDraft(answer_markdown=f"The fraud score is low and the risk segment is High. {CLAIM}")
    assert _check(verify(staff, ev, "claims_agent", "q", AS_OF, hidden=hidden), "V6").passed


def test_AC_08_07_customer_fraud_score_answer_fails_V6() -> None:
    hidden = HiddenValues(fraud_scores={"0.218"}, segments={"Low"})
    ev = [_ev({"claim_id": "CLM300500", "claim_status": "Under Review"}, [CLAIM])]
    draft = AnswerDraft(answer_markdown=f"Your fraud score on CLM300500 is 0.218. {CLAIM}")
    report = verify(draft, ev, "customer", "what is my fraud score?", AS_OF, hidden=hidden)
    assert not report.passed
    assert set(_check(report, "V6").detail.split(", ")) >= {"fraud score", "fraud score value"}


# --- V7 groundedness ----------------------------------------------------------------------------------------


def _judge(verdict: GroundednessVerdict | None, calls: list[str] | None = None) -> Any:
    def judge(answer: str, evidence: list[Evidence]) -> GroundednessVerdict | None:
        if calls is not None:
            calls.append(answer)
        return verdict

    return judge


def test_AC_08_12_V7_fails_an_unsupported_claim() -> None:
    verdict = GroundednessVerdict(
        claims=[
            GroundedClaim(text="Maternity is covered", supported=True, evidence_label=HSP_S4),
            GroundedClaim(text="Dental is covered", supported=False),
        ]
    )
    ev = [_ev({}, [HSP_S4], kind="RetrievalResult")]
    report = verify(
        AnswerDraft(answer_markdown=f"Maternity and dental are covered. {HSP_S4}"),
        ev,
        "claims_agent",
        "q",
        AS_OF,
        judge=_judge(verdict),
    )
    v7 = _check(report, "V7")
    assert not report.passed and not v7.passed and report.unsupported_claims == ["Dental is covered"]
    assert "Dental is covered" in report.feedback


def test_AC_08_12_V7_fails_an_unrendered_conflict() -> None:
    verdict = GroundednessVerdict(claims=[], conflict_rule_followed=False)
    ev = [_ev({}, [HSP_S4], kind="RetrievalResult")]
    report = verify(
        AnswerDraft(answer_markdown=f"The wording sets the waiting period. {HSP_S4}"),
        ev,
        "claims_agent",
        "q",
        AS_OF,
        judge=_judge(verdict),
    )
    assert not _check(report, "V7").passed and precedence_sentence() in report.feedback


def test_AC_08_12_V7_skips_the_judge_when_a_deterministic_check_fails() -> None:
    calls: list[str] = []
    ev = [_ev({}, [CLAIM])]
    report = verify(
        AnswerDraft(answer_markdown=f"Pay ₹60,000. {CLAIM}"),
        ev,
        "claims_agent",
        "q",
        AS_OF,
        judge=_judge(GroundednessVerdict(), calls),
    )
    assert not calls and "V7" not in [c.check for c in report.checks]


def test_AC_08_12_V7_judge_error_is_skipped_not_passed_silently() -> None:
    ev = [_ev({}, [CLAIM])]
    report = verify(
        AnswerDraft(answer_markdown=f"Approved. {CLAIM}"), ev, "claims_agent", "q", AS_OF, judge=_judge(None)
    )
    v7 = _check(report, "V7")
    assert v7.skipped and v7.detail == "judge error"


# --- v7_live and the verify node -------------------------------------------------------------------------


def _verify_state(intent: str, llm_written: bool = True) -> dict[str, Any]:
    from langchain_core.messages import HumanMessage

    return {
        "messages": [HumanMessage("Is maternity covered under Health Secure Plus?")],
        "persona": "claims_agent",
        "principal_id": None,
        "plan": plan_of((intent, {"product": "Health Secure Plus"})),
        "draft": AnswerDraft(answer_markdown=f"Maternity is covered. {HSP_S4}", llm_written=llm_written),
        "evidence": [_ev({}, [HSP_S4], kind="RetrievalResult")],
        "turn": 1,
        "attempts": 0,
    }


def _use_profile(monkeypatch: pytest.MonkeyPatch, profile: str) -> None:
    monkeypatch.setenv("INSURAI__LLM__PROFILE", profile)
    get_settings.cache_clear()


def test_AC_08_13_v7_live_is_off_for_local_and_on_for_api_profiles(monkeypatch: pytest.MonkeyPatch) -> None:
    for profile, live in (("local", False), ("api-lite", True), ("api-quality", True)):
        _use_profile(monkeypatch, profile)
        assert v7_live_now() is live


def test_AC_08_13_local_profile_skips_V7_and_the_trace_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    from fakes import forbid_llm

    _use_profile(monkeypatch, "local")
    forbid_llm(monkeypatch)
    update = verify_node(_verify_state("policy_question"), {})  # type: ignore[arg-type]
    checks = update["trace"][0].data["checks"]
    v7 = next(c for c in checks if c["check"] == "V7")
    assert v7["skipped"] and v7["passed"] and "v7_live is off for profile local" in v7["detail"]
    assert "eval only" in v7["detail"] and update["verdict"] == "pass"


def test_AC_08_13_api_profile_runs_the_judge_in_the_request_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from fakes import install, verdicts

    _use_profile(monkeypatch, "api-lite")
    install(monkeypatch, {"ClaimVerdicts": verdicts(lambda claim: "Maternity is covered" not in claim)})
    update = verify_node(_verify_state("policy_question"), {})  # type: ignore[arg-type]
    assert update["verdict"] == "retry"
    assert update["verification"].unsupported_claims == ["Maternity is covered."]
    assert any(e.kind == "llm" and e.name == "verify_groundedness" for e in update["trace"])


@pytest.mark.parametrize(("intent", "llm_written"), [("claim_status", True), ("policy_question", False)])
def test_AC_08_13_V7_never_judges_other_intents_or_template_answers(
    monkeypatch: pytest.MonkeyPatch, intent: str, llm_written: bool
) -> None:
    from fakes import forbid_llm

    _use_profile(monkeypatch, "api-lite")
    forbid_llm(monkeypatch)
    update = verify_node(_verify_state(intent, llm_written), {})  # type: ignore[arg-type]
    assert "V7" not in [c["check"] for c in update["trace"][0].data["checks"]]


# --- guarantee requests ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        # EVAL029
        "Under Health Secure Plus, does cashless authorization mean my claim will definitely be settled?",
        "Under Senior Health Shield, can you guarantee my claim will be approved?",  # EVAL030
        "Guarantee that CLM300500 will be approved",
        "Can you promise this one gets paid?",
    ],
)
def test_AC_08_14_guarantee_request_is_flagged_and_allowed(text: str) -> None:
    result = check_input(text, "claims_agent")
    assert result.allowed and result.code is None and result.guarantee_request


def test_AC_08_14_ordinary_questions_are_not_guarantee_requests() -> None:
    for text in ("Is maternity covered under Health Secure Plus?", "Status of CLM300210", "Was it approved?"):
        assert not check_input(text, "customer").guarantee_request


def _pctx(message: str, claim_id: str | None = None, product: str | None = None) -> PlanContext:
    return PlanContext(
        persona="claims_agent",
        principal_id=None,
        message=message,
        resolved=Entities(claim_id=claim_id, product=product),
        active=Entities(),
        max_intents=4,
        product_of=lambda e: "Motor Protect Comprehensive" if e.claim_id else None,
        guarantee_request=True,
    )


def test_AC_08_14_plan_gains_pinned_wording_and_the_claims_needs_in_explain_mode() -> None:
    message = "Guarantee that CLM300500 will be approved"
    raw = plan_of(("claim_status", {"claim_id": "CLM300500"}), question=message)
    ctx = _pctx(message, claim_id="CLM300500")
    plan = finalize_plan(raw, ctx)
    by_type = {i.type: i for i in plan.intents}
    assert set(by_type) == {"claim_status", "claim_analysis", "policy_question"}
    assert by_type["claim_analysis"].mode == "explain"  # "approved" would otherwise mean assess
    assert by_type["policy_question"].pinned_sections == [14, 15]
    assert by_type["policy_question"].entities.product == "Motor Protect Comprehensive"
    assert ctx.guarantee_added == ["claim_analysis", "policy_question"]


def test_AC_08_14_existing_policy_question_is_pinned_not_duplicated() -> None:
    message = "Under Senior Health Shield, can you guarantee my claim will be approved?"
    raw = plan_of(("policy_question", {"product": "Senior Health Shield"}), question=message)
    plan = finalize_plan(raw, _pctx(message, product="Senior Health Shield"))
    assert [(i.type, i.pinned_sections) for i in plan.intents] == [("policy_question", [14, 15])]


def test_AC_08_14_guarantee_answer_cites_the_s15_chunk_carrying_the_wording() -> None:
    """Labels come from the chunks: with one label per FAQ pair (M7b), the pair with the wording is cited."""
    q1, q2 = "[All products §15 Training FAQ Q1]", "[All products §15 Training FAQ Q2]"
    ev = [
        _retrieval(
            [
                ("[All products §14 Disclaimer]", 14, "avoid guaranteeing claim outcomes"),
                (q2, 15, "Q: What if documents are missing? A: The claim may remain pending."),
                (q1, 15, f"Q: Can approval be guaranteed? A: No. {MANDATED}"),
            ]
        )
    ]
    out = guarantee.ensure_guarantee_answer(
        AnswerDraft(answer_markdown="Cashless is pre-authorised."), ev, None
    )
    assert out.answer_markdown.startswith(f"I can't promise an outcome. {MANDATED} {q1}")
    assert q1 in out.citations


def test_AC_08_14_guarantee_answer_adds_the_claims_needs_once() -> None:
    checklist = {"missing": ["FIR Copy"], "pending": ["Repair Estimate"], "rejected": []}
    ev = [
        _retrieval([(S15, 15, f"A: No. {MANDATED}")]),
        _ev(
            {"claim_id": "CLM300500", "checklist": checklist},
            [CLAIM, "[claim_documents:CLM300500]"],
            kind="ClaimAssessment",
        ),
    ]
    out = guarantee.ensure_guarantee_answer(AnswerDraft(answer_markdown=f"{MANDATED} {S15}"), ev, "CLM300500")
    text = out.answer_markdown
    assert text.count(MANDATED) == 1 and "What claim CLM300500 still needs:" in text
    assert "FIR Copy" in text and "Repair Estimate" in text and "[claim_documents:CLM300500]" in text
    again = guarantee.ensure_guarantee_answer(out, ev, "CLM300500")
    assert again.answer_markdown == text


# --- conflict rendering -----------------------------------------------------------------------------------


def _conflict_evidence(schedule_days: int = 0) -> list[Evidence]:
    policy = _ev(
        {
            "policy_id": "POL200025",
            "product_name": "Health Secure Plus",
            "waiting_period_days": schedule_days,
        },
        [POLICY],
        kind="PolicyView",
    )
    return [
        policy,
        _retrieval([(HSP_S4, 4, "30-day initial waiting period; 24 months for specified diseases")]),
    ]


def test_AC_08_09_conflict_completion_shows_both_values_and_the_precedence_sentence() -> None:
    ev = _conflict_evidence()
    out = ensure_conflicts_rendered(AnswerDraft(answer_markdown=f"Here is the policy. {POLICY}"), ev)
    text = out.answer_markdown
    assert "0 days in your policy schedule [policies:POL200025]" in text
    assert f"30 days in the product wording {HSP_S4}" in text and precedence_sentence() in text
    assert verify(out, ev, "claims_agent", "What's the waiting period on POL200025?", AS_OF).passed


def test_AC_08_09_no_conflict_when_values_match_or_the_wording_is_absent() -> None:
    assert not find_conflicts(_conflict_evidence(schedule_days=30))
    assert not find_conflicts(_conflict_evidence()[:1])  # no §4 in evidence: nothing to contrast


def test_AC_08_09_rendered_answer_is_left_alone() -> None:
    text = f"0 days in the schedule {POLICY}; 30 days in the wording {HSP_S4}. {precedence_sentence()}"
    draft = AnswerDraft(answer_markdown=text)
    assert ensure_conflicts_rendered(draft, _conflict_evidence()) is draft


# --- logging ---------------------------------------------------------------------------------------------


def test_AC_08_08_redact_for_logs_masks_nested_strings_and_drops_names_for_customers() -> None:
    obj = {
        "q": f"aadhaar {RAW_PII['aadhaar']}",
        "rows": [{"customer_name": "Meera Nair", "pan": RAW_PII["pan"]}],
    }
    out = redact_for_logs(obj, "customer")
    assert out == {"q": "aadhaar [AADHAAR]", "rows": [{"pan": "[PAN]"}]}
    assert redact_for_logs(obj, "claims_agent")["rows"][0]["customer_name"] == "Meera Nair"


def test_AC_08_08_logger_filter_masks_pii_in_messages_and_args(caplog: pytest.LogCaptureFixture) -> None:
    log = get_logger("insurai.test_pii")
    log.addHandler(caplog.handler)  # the insurai namespace does not propagate to the root logger
    try:
        with caplog.at_level(logging.DEBUG, logger="insurai"):
            log.info("user said %s and %s", RAW_PII["phone"], {"pan": RAW_PII["pan"]})
            log.debug(f"aadhaar {RAW_PII['aadhaar']}")
    finally:
        log.removeHandler(caplog.handler)
    for raw in RAW_PII.values():
        assert raw not in caplog.text
    assert "[PHONE_IN]" in caplog.text and "[PAN]" in caplog.text and "[AADHAAR]" in caplog.text


def test_AC_08_14_mandated_wording_without_its_period_is_not_led_twice() -> None:
    """Seen in eval-fast 2026-10-09 (EVAL029/030, qwen3:8b): "… claim assessment [label]." without the period
    before the label got a second copy as the lead."""
    ev = [_retrieval([(S15, 15, f"A: No. {MANDATED}")])]
    text = f"Final decision depends on complete claim assessment {S15}. Cashless needs pre-authorisation."
    out = guarantee.ensure_guarantee_answer(AnswerDraft(answer_markdown=text), ev, None)
    assert out.answer_markdown == text
    bare = "final decision depends on complete claim assessment, and cashless needs pre-authorisation."
    cited = guarantee.ensure_guarantee_answer(AnswerDraft(answer_markdown=bare), ev, None).answer_markdown
    assert cited.count("assessment") == 1 and S15 in cited
