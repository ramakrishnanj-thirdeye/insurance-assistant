"""M7 fixes (spec 08): currency check, fixed sentences only on their trigger, the V7 splitter's non-claims,
idempotent appended blocks, and the qualifier rule in the prompts. No warehouse, no LLM."""

from types import SimpleNamespace
from typing import Any

import pytest
from fakes import plan_of

from insurai.agent.prompts import load_prompt, template
from insurai.agent.respond import final_text
from insurai.agent.schemas import AnswerDraft, Evidence
from insurai.agent.synthesize import clean_fixed_sentences
from insurai.guardrails.currency import currency_hits
from insurai.guardrails.fixed import mandated_once, mandated_wording, precedence_sentence, strip_untriggered
from insurai.guardrails.groundedness import atomic_claims, claim_key, non_claims
from insurai.guardrails.verify import rewrite_guarantees, verify
from insurai.rules.schemas import ReviewDecision
from insurai.textblocks import append_once, dedupe_paragraphs
from insurai.tools.sources import sql_source

pytestmark = pytest.mark.unit

CA005_SENTENCE = (
    "The claim's status is Partially Approved with an approved amount of $56,714 out of $131,115 requested."
)
CLAIM = {"claim_id": "CLM300012", "claim_status": "Partially Approved", "approved_amount": 56714}


def _claim_ev() -> Evidence:
    return Evidence(
        intent_id="i1",
        worker="claim_tools",
        kind="ClaimView",
        payload={**CLAIM, "claim_amount": 131115},
        sources=[sql_source("claims", "CLM300012")],
        summary="",
    )


# --- AC-08-17 currency ------------------------------------------------------------------------------------


def test_AC_08_17_dollar_amounts_from_the_ca005_narrative_fail_with_feedback() -> None:
    assert currency_hits(CA005_SENTENCE) == ["$56,714", "$131,115"]
    draft = AnswerDraft(answer_markdown=CA005_SENTENCE + " [claims:CLM300012]")
    report = verify(draft, [_claim_ev()], "claims_agent", "Assess CLM300012")
    currency = next(c for c in report.checks if c.check == "CURRENCY")
    assert not report.passed and not currency.passed and currency.detail == "$56,714, $131,115"
    assert "rupees" in report.feedback and "$56,714" in report.feedback
    v3 = next(c for c in report.checks if c.check == "V3")
    assert v3.passed  # the digits are evidence; only the currency is wrong


@pytest.mark.parametrize(
    "text", ["USD 500 is payable", "Rs. 5,000 was approved", "€20", "50 dollars", "INR 500"]
)
def test_AC_08_17_other_currencies_fail(text: str) -> None:
    assert currency_hits(text)


def test_AC_08_17_rupee_amounts_and_labels_pass() -> None:
    text = (
        "Approved ₹56,714 of ₹1,31,115 [claims:CLM300012]; "
        "sum insured ₹5,00,000 [Health Secure Plus §2 Sum Insured]."
    )
    assert currency_hits(text) == []
    draft = AnswerDraft(answer_markdown="Approved ₹56,714 of ₹1,31,115 [claims:CLM300012].")
    report = verify(draft, [_claim_ev()], "claims_agent", "Assess CLM300012")
    assert report.passed, report.feedback


# --- AC-08-18 fixed sentences only where their trigger applies ----------------------------------------------


def test_AC_08_18_precedence_sentence_stripped_without_a_conflict_kept_once_with_one() -> None:
    rule = precedence_sentence()
    text = f"Pets are not covered [All products §9 Exclusions]. {rule}\n\nMore. {rule}"
    assert precedence_sentence() not in strip_untriggered(text, conflict=False, mandated_allowed=False)
    kept = strip_untriggered(text, conflict=True, mandated_allowed=False)
    assert kept.count(precedence_sentence()) == 1 and kept.startswith("Pets are not covered")


def test_AC_08_18_mandated_wording_only_on_guarantee_or_after_v4() -> None:
    text = f"Dental is covered after an accident [Family Care Gold §9 Exclusions].\n{mandated_wording()}"
    plain = strip_untriggered(text, conflict=False, mandated_allowed=False)
    assert mandated_wording() not in plain and plain.startswith("Dental is covered")
    assert mandated_wording() in strip_untriggered(text, conflict=False, mandated_allowed=True)
    rewritten = rewrite_guarantees("Your claim will definitely be approved.")
    assert rewritten == mandated_wording()  # V4 puts it back; verify runs after the strip


def test_AC_08_18_synthesizer_strips_by_turn_trigger() -> None:
    labelled = f"{mandated_wording()[:-1]} [All products §15 Training FAQ Q2]."
    text = f"The wording says so [All products §6 Hospitalization / Loss Coverage].\n{labelled}"
    plain = {"guard": SimpleNamespace(guarantee_request=False), "plan": plan_of(("policy_question", {}))}
    guarantee = {"guard": SimpleNamespace(guarantee_request=True), "plan": plan_of(("policy_question", {}))}
    assert "Final decision" not in clean_fixed_sentences(plain, text, [])  # type: ignore[arg-type]
    assert "Final decision" in clean_fixed_sentences(guarantee, text, [])  # type: ignore[arg-type]


# --- AC-08-19 V7 splitter -----------------------------------------------------------------------------------


def test_AC_08_19_splitter_skips_table_headers_separators_and_system_sentences() -> None:
    answer = "\n".join(
        [
            "| Document Type | Description |",
            "|---|---|",
            "| Claim Form | Signed form [All products §8 Reimbursement Process] |",
            "",
            "Next steps:",
            "- Submit the claim form [All products §8 Reimbursement Process].",
            precedence_sentence(),
            mandated_wording(),
            template("specialist_review_customer"),
            template("guarantee_lead", label="").strip(),
            template("review_decision", action="approve", note="Reviewed and approved."),
        ]
    )
    claims = atomic_claims(answer)
    assert claims == ["| Claim Form | Signed form |", "Submit the claim form."]
    skipped = non_claims(answer)
    for text in (
        "Document Type | Description",
        precedence_sentence(),
        "A claims specialist will review this claim before a decision.",
    ):
        assert claim_key(text) in skipped


def test_AC_08_19_abstention_wording_is_not_a_claim() -> None:
    from insurai.agent.synthesize import abstain_draft

    ev = Evidence(
        intent_id="i1",
        worker="policy_rag",
        kind="RetrievalResult",
        payload={"confident": False},
        sources=[sql_source("claims", "CLM300012")],
        summary="Closest clauses: Maternity Protect §9 Exclusions",
    )
    claims = atomic_claims(abstain_draft([ev]).answer_markdown)
    assert claims == ["Closest clauses: Maternity Protect §9 Exclusions"]  # EVAL032: only the evidence line


def test_AC_08_19_judge_claims_on_skipped_lines_are_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    from fakes import install

    from insurai.guardrails.groundedness import judge_groundedness

    answer = (
        "| Document Type | Description |\n|---|---|\n| Bills | Hospital bills |\n\n" + precedence_sentence()
    )
    verdict = {
        "claims": [
            {"text": "Document Type | Description", "supported": False},
            {"text": precedence_sentence(), "supported": False},
            {"text": "Bills | Hospital bills", "supported": True},
        ]
    }
    install(monkeypatch, {"GroundednessVerdict": lambda m: verdict})
    result, _ = judge_groundedness(answer, [])
    assert [c.text for c in result.claims] == ["Bills | Hospital bills"]


# --- AC-08-20 idempotent blocks -----------------------------------------------------------------------------


def test_AC_08_20_append_once_and_dedupe() -> None:
    block = "Reviewer decision: **approve**. Reviewer note: Reviewed and approved."
    once = append_once("Answer.", block)
    assert append_once(once, block) == once
    para = "Line one [policies:POL1]  \nLine two [All products §8 Reimbursement Process]"
    assert dedupe_paragraphs(f"{para}\n\nOther.\n\n{para}\n\n{para}").count("Line one") == 1
    assert dedupe_paragraphs("Text.\n\nNext steps:") == "Text."  # an empty heading is dropped
    table = "| A | B |\n|---|---|\n| x | 1 |\n| x | 1 |"
    assert dedupe_paragraphs(table) == table  # table rows are never deduplicated


def _respond_state(**extra: Any) -> dict[str, Any]:
    return {
        "persona": "claims_agent",
        "plan": plan_of(("claim_analysis", {"claim_id": "CLM300012"})),
        **extra,
    }


def test_AC_08_20_respond_never_repeats_the_review_line() -> None:
    decision = ReviewDecision(action="approve", note="Reviewed and approved.")
    line = template("review_decision", action="approve", note="Reviewed and approved.")
    draft = AnswerDraft(answer_markdown=f"Narrative.\n\n{line}")
    text = final_text(_respond_state(draft=draft, review=decision))  # type: ignore[arg-type]
    assert text.count(line) == 1


def test_AC_08_20_mandated_sentence_at_most_once_on_a_guarantee_turn_for_a_customer() -> None:
    lead = template("guarantee_lead", label="[All products §15 Training FAQ Q2]")
    draft = AnswerDraft(answer_markdown=f"{lead}\n\nWhat the claim still needs: Claim Form.")
    state = _respond_state(
        draft=draft, persona="customer", assessment=SimpleNamespace(needs_human_review=True)
    )
    text = final_text(state)  # type: ignore[arg-type]
    assert text.count("Final decision depends on complete claim assessment") == 1
    assert "A claims specialist will review this claim before a decision." in text
    assert mandated_once(text) == text


# --- AC-08-21 qualifiers ------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["synthesize", "dossier_narrative"])
def test_AC_08_21_prompts_keep_policy_qualifiers(name: str) -> None:
    body = load_prompt(name).body
    assert "never harden" in body and "normally, may, subject to, unless" in body
    assert "must be submitted within N days" in body
