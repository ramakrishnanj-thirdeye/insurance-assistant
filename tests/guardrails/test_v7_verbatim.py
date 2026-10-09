"""V7 verbatim pre-check (spec 08, M7b): claims found word for word in the evidence settle without the judge;
and the per-pair §15 FAQ labels pass V1."""

from datetime import date
from typing import Any

import pytest
from fakes import install

from insurai.agent.schemas import AnswerDraft, Evidence
from insurai.guardrails.groundedness import atomic_claims, judge_groundedness, normalise, verbatim_settled
from insurai.guardrails.verify import labels_in, strip_labels, verify
from insurai.tools.schemas import SourceRef

pytestmark = pytest.mark.unit

CSP9 = "[Car Shield Plus §9 Exclusions]"
FAQ_Q2 = "[All products §15 Training FAQ Q2]"
WORDING = "Depreciation unless zero-dep add-on active, illegal use, racing, breakdown unrelated to accident."


def _ev(text: str = WORDING, label: str = CSP9) -> list[Evidence]:
    ref = SourceRef(kind="policy", label=label)
    payload = {"clauses": [{"text": text}], "narrative": "Model-written: dental is covered for everyone."}
    return [
        Evidence(
            intent_id="i1", worker="w", kind="RetrievalResult", payload=payload, sources=[ref], summary=""
        )
    ]


def _judge_calls(monkeypatch: pytest.MonkeyPatch, verdict: dict[str, Any]) -> list[str]:
    seen: list[str] = []

    def judge(messages: list[Any]) -> dict[str, Any]:
        seen.append(str(messages[0].content))
        return verdict

    install(monkeypatch, {"GroundednessVerdict": judge})
    return seen


def test_atomic_claims_split_sentences_and_bullets_without_labels_or_fixed_sentences() -> None:
    answer = (
        "I can't promise an outcome. Final decision depends on complete claim assessment. " + FAQ_Q2 + "\n"
        f"- **Racing** is excluded {CSP9}.\n1. Illegal use is excluded too. Ask again."
    )
    assert atomic_claims(answer) == ["**Racing** is excluded.", "Illegal use is excluded too.", "Ask again."]
    assert normalise(f"**Racing** is  EXCLUDED {CSP9}.") == "racing is excluded"


def test_AC_08_15_v7_verbatim_claim_settled_without_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _judge_calls(monkeypatch, {"claims": [{"text": "Racing is not covered", "supported": False}]})
    answer = "\n".join(
        [
            f"Breakdown unrelated to accident is excluded? No: {CSP9}",
            f"Illegal use, racing, breakdown unrelated to accident. {CSP9}",
            f"Racing is not covered. {CSP9}",
        ]
    )
    verdict, call = judge_groundedness(answer, _ev())
    verbatim = [c.text for c in verdict.claims if c.settled_by == "verbatim"]
    assert verbatim == ["Illegal use, racing, breakdown unrelated to accident."]
    assert call is not None and len(seen) == 1
    assert "- Illegal use, racing, breakdown unrelated to accident." in seen[0]  # told to skip it
    assert [c.text for c in verdict.claims if not c.supported] == ["Racing is not covered"]


def test_AC_08_15_v7_judge_claims_repeating_a_settled_one_are_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _judge_calls(
        monkeypatch,
        {
            "claims": [
                {"text": "illegal use, racing, breakdown unrelated to accident", "supported": True},
                {"text": "Dental is covered", "supported": False},
            ]
        },
    )
    verdict, _ = judge_groundedness(
        f"Illegal use, racing, breakdown unrelated to accident. {CSP9} Dental is covered.", _ev()
    )
    assert [(c.settled_by, c.supported) for c in verdict.claims] == [("verbatim", True), ("judge", False)]


def test_AC_08_15_v7_short_claims_are_not_settled() -> None:
    assert verbatim_settled(["Racing.", "Illegal use, racing."], _ev()) == []  # under 4 words
    assert verbatim_settled(["Illegal use, racing, breakdown"], _ev()) == ["Illegal use, racing, breakdown"]


def test_AC_08_15_v7_model_written_payload_is_not_evidence() -> None:
    assert verbatim_settled(["Dental is covered for everyone."], _ev()) == []


def test_AC_08_15_v7_all_settled_skips_the_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _judge_calls(monkeypatch, {"claims": []})
    verdict, call = judge_groundedness(f"Illegal use, racing, breakdown unrelated to accident. {CSP9}", _ev())
    assert call is None and seen == []
    assert len(verdict.claims) == 1 and verdict.claims[0].supported


def test_AC_08_16_v1_accepts_the_faq_pair_label() -> None:
    text = f"The claim may remain pending until required documents are received. {FAQ_Q2}"
    assert labels_in(text) == [FAQ_Q2]
    assert FAQ_Q2 not in strip_labels(text)
    q2 = "Q: What if documents are missing? A: " + text.removesuffix(f" {FAQ_Q2}")
    report = verify(
        AnswerDraft(answer_markdown=text), _ev(q2, FAQ_Q2), "claims_agent", "q", date(2026, 10, 1)
    )
    v1 = next(c for c in report.checks if c.check == "V1")
    assert v1.passed and report.invalid_citations == []
