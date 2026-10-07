"""Template answers (spec 06, AC-06-21, AC-06-22) on hand-built evidence: no warehouse, no LLM."""

from typing import Any

import pytest
from fakes import plan_of

from insurai.agent.answers import template_draft
from insurai.agent.schemas import Evidence
from insurai.agent.synthesize import deterministic_draft, with_premise_correction
from insurai.eval.e2e_sql_facts import states_none_missing
from insurai.guardrails.verify import verify
from insurai.tools.sources import sql_source

pytestmark = pytest.mark.unit

CLAIM = {
    "claim_id": "CLM300210",
    "claim_status": "Approved",
    "approved_amount": 64577,
    "claim_date": "2026-03-02",
    "claim_amount": 70000,
    "product_name": "Health Secure Plus",
    "policy_id": "POL218917",
    "rejection_or_adjustment_reason": None,
    "customer_name": None,  # hidden from the customer persona
}
DOCS = {
    "claim_id": "CLM300210",
    "policy_type": "Health",
    "missing": [],
    "pending": ["Prescription"],
    "rejected": [],
    "untracked": ["Pre-authorization form"],
}


def _ev(kind: str, payload: dict[str, Any], *refs: tuple[str, str], intent_id: str = "i1") -> Evidence:
    return Evidence(
        intent_id=intent_id,
        worker="claim_tools",
        kind=kind,
        payload=payload,
        sources=[sql_source(t, k) for t, k in refs],
        summary="",
    )


def _claim(**changes: Any) -> Evidence:
    return _ev("ClaimView", CLAIM | changes, ("claims", "CLM300210"), ("policies", "POL218917"))


def test_AC_06_21_claim_status_template_is_cited_and_verifies() -> None:
    plan = plan_of(("claim_status", {"claim_id": "CLM300210"}))
    draft = template_draft(plan, [_claim()], "What is the status of CLM300210?")
    assert draft is not None
    assert draft.answer_markdown.startswith("Claim CLM300210 is **Approved**, with ₹64,577 approved.")
    assert draft.citations == ["[claims:CLM300210]"] and "None" not in draft.answer_markdown
    assert verify(draft, [_claim()], "claims_agent", "status?").passed


def test_AC_06_21_zero_approved_is_stated_and_none_is_never_rendered() -> None:
    plan = plan_of(("claim_status", {"claim_id": "CLM300210"}))
    zero = template_draft(plan, [_claim(approved_amount=0, claim_status="Rejected")], "status?")
    unknown = template_draft(plan, [_claim(approved_amount=None, claim_status="Submitted")], "status?")
    assert zero is not None and "with ₹0 approved" in zero.answer_markdown
    assert unknown is not None and "approved" not in unknown.answer_markdown
    assert "None" not in unknown.answer_markdown


def test_AC_06_21_a_missing_required_field_means_no_template() -> None:
    plan = plan_of(("claim_status", {"claim_id": "CLM300210"}))
    assert template_draft(plan, [_claim(product_name=None)], "status?") is None


def test_AC_06_21_empty_missing_list_says_no_documents_are_missing() -> None:
    plan = plan_of(("claim_documents", {"claim_id": "CLM300210"}))
    ev = _ev("DocumentChecklist", DOCS, ("claim_documents", "CLM300210"))
    draft = template_draft(plan, [ev], "Which documents are missing?")
    assert draft is not None
    assert draft.answer_markdown.startswith("No documents are missing for claim CLM300210.")
    assert states_none_missing(draft.answer_markdown.casefold())
    assert "Prescription" in draft.answer_markdown and "Pre-authorization form" in draft.answer_markdown
    assert verify(draft, [ev], "claims_agent", "Which documents are missing?").passed


def test_AC_06_21_missing_documents_are_listed() -> None:
    plan = plan_of(("claim_documents", {"claim_id": "CLM300210"}))
    ev = _ev(
        "DocumentChecklist", DOCS | {"missing": ["Claim Form", "ID Proof"]}, ("claim_documents", "CLM300210")
    )
    draft = template_draft(plan, [ev], "q")
    assert (
        draft is not None
        and "missing these required documents: Claim Form, ID Proof" in draft.answer_markdown
    )


def test_AC_06_21_only_single_sql_fact_intents_get_a_template() -> None:
    mixed = plan_of(
        ("claim_status", {"claim_id": "CLM300210"}), ("claim_interactions", {"claim_id": "CLM300210"})
    )
    interactions = plan_of(("claim_interactions", {"claim_id": "CLM300210"}))
    assert template_draft(mixed, [_claim()], "q") is None
    assert template_draft(interactions, [_claim()], "q") is None


def test_AC_06_21_verify_retry_goes_to_the_generator() -> None:
    plan = plan_of(("claim_status", {"claim_id": "CLM300210"}))
    state: dict[str, Any] = {"plan": plan, "messages": [], "attempts": 0}
    assert deterministic_draft(state, [_claim()]) is not None  # type: ignore[arg-type]
    assert deterministic_draft(state | {"attempts": 1}, [_claim()]) is None  # type: ignore[arg-type]


def test_AC_06_22_claim_status_template_corrects_a_false_premise() -> None:
    plan = plan_of(("claim_status", {"claim_id": "CLM300210"}))
    draft = template_draft(plan, [_claim()], "Is CLM300210 pending?")
    assert draft is not None
    assert draft.answer_markdown.startswith("CLM300210 is Approved, not pending [claims:CLM300210].")
    assert verify(draft, [_claim()], "claims_agent", "Is CLM300210 pending?").passed


def test_AC_06_22_generated_answer_on_a_mixed_turn_gets_the_correction() -> None:
    plan = plan_of(
        ("claim_status", {"claim_id": "CLM300210"}), ("claim_interactions", {"claim_id": "CLM300210"})
    )
    text = with_premise_correction(
        "Here it is. [claims:CLM300210]", plan, [_claim()], "Is CLM300210 pending?"
    )
    assert text.startswith("CLM300210 is Approved, not pending [claims:CLM300210].")
    assert with_premise_correction("ok", plan, [_claim()], "Is CLM300210 approved?") == "ok"
