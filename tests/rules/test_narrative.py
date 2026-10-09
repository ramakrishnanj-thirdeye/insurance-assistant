"""Dossier text (spec 07 Behaviour 9, spec 06 explain vs assess): mode, premise, completeness guard, fallback
rendering, and AC-07-07 must_mention coverage with scripted narratives (any model output passes the guard).
"""

import json
import re
from typing import Any

import pytest
from claim_items import all_items, item_ids, seed_items
from fakes import install

from insurai.agent.dossier import analyze
from insurai.rules.engine import evaluate_claim
from insurai.rules.narrative import (
    complete_narrative,
    complete_narrative_with_additions,
    narrative_input,
    premise_correction,
    question_mode,
    render_assessment,
)
from insurai.rules.schemas import ClaimAssessment
from insurai.tools.schemas import ToolContext


@pytest.mark.unit
@pytest.mark.parametrize(
    ("question", "mode"),
    [
        ("Analyze claim CLM300210 and tell me if documents are missing.", "assess"),
        ("Please analyse CLM300210", "assess"),
        ("Review CLM300210", "assess"),
        ("Should we approve CLM300210?", "assess"),
        ("Decide on CLM300210", "assess"),
        ("Why is my claim pending?", "explain"),
        ("Give me a summary of this claim", "explain"),
        ("Why is CLM300210 under review?", "explain"),  # a status, not a request to review
        ("Is CLM300210 approved?", "explain"),
        ("Which documents are pending verification for CLM300210?", "explain"),
    ],
)
def test_question_mode_explain_vs_assess(question: str, mode: str) -> None:
    assert question_mode(question) == mode


@pytest.mark.unit
@pytest.mark.parametrize(
    ("question", "status", "expected"),
    [
        ("Why is CLM300210 pending?", "Approved", "CLM300210 is Approved, not pending [claims:CLM300210]."),
        (
            "Why was CLM300210 rejected?",
            "Approved",
            "CLM300210 is Approved, not rejected [claims:CLM300210].",
        ),
        (
            "Why is CLM300210 under review?",
            "Approved",
            "CLM300210 is Approved, not under review [claims:CLM300210].",
        ),
        ("Why is CLM300210 pending?", "Under Review", None),  # pending covers Under Review
        ("Why was CLM300210 approved or rejected?", "Rejected", None),  # one status fits
        ("Which documents are pending verification on CLM300210?", "Approved", None),
        ("Summarise CLM300210", "Approved", None),
    ],
)
def test_premise_correction(question: str, status: str, expected: str | None) -> None:
    assert premise_correction(question, "CLM300210", status) == expected


def _assessment(claim_id: str) -> ClaimAssessment:
    result = evaluate_claim(claim_id, "claims_agent")
    assert isinstance(result, ClaimAssessment)
    return result


@pytest.mark.integration
def test_complete_narrative_puts_correction_first_and_appends_missing(warehouse_ready: None) -> None:
    a = _assessment("CLM300210")
    correction = premise_correction("Why is CLM300210 pending?", a.claim_id, a.facts["claim_status"])
    assert correction
    text = complete_narrative(f"Summary. {correction} [claims:CLM300210]", a, correction)
    assert text.startswith(correction) and text.count(correction) == 1
    for r in a.rules:
        if r.status in ("fail", "review"):
            assert r.message in text
    assert all(action in text for action in a.next_best_actions)


@pytest.mark.integration
def test_complete_narrative_leaves_a_complete_text_alone(warehouse_ready: None) -> None:
    a = _assessment("CLM300101")
    body = "\n".join(
        ["Claim CLM300101 is Approved. [claims:CLM300101]"]
        + [f"- {r.message} [claims:CLM300101]" for r in a.rules if r.message]
        + a.next_best_actions
    )
    assert complete_narrative(body, a) == body


@pytest.mark.integration
def test_AC_11_17_guard_reports_what_it_appended(warehouse_ready: None) -> None:
    complete = _assessment("CLM300101")
    body = "\n".join(
        ["Claim CLM300101 is Approved. [claims:CLM300101]"]
        + [f"- {r.message} [claims:CLM300101]" for r in complete.rules if r.message]
        + complete.next_best_actions
    )
    assert complete_narrative_with_additions(body, complete) == (body, [])
    control = _assessment("CLM300423")
    text, added = complete_narrative_with_additions("Nothing stands out. [claims:CLM300423]", control)
    assert added == ["Claim CLM300423 is Under Review [claims:CLM300423]."] and text.startswith(added[0])


@pytest.mark.integration
def test_complete_narrative_states_the_status_when_missing(warehouse_ready: None) -> None:
    a = _assessment("CLM300423")  # the control claim: no findings, no actions
    text = complete_narrative("Nothing stands out. [claims:CLM300423]", a)
    assert text.startswith("Claim CLM300423 is Under Review [claims:CLM300423].")


@pytest.mark.integration
def test_render_assessment_is_cited_and_complete(warehouse_ready: None) -> None:
    a = _assessment("CLM300210")
    text = render_assessment(a)
    assert text.startswith("Claim CLM300210 is Approved; the assessment found 5 findings, 2 of them blockers")
    assert "[All products §8 Reimbursement Process]" in text and "[policies:POL218917]" in text
    assert "₹58,119" in text and "Next steps:" in text


# --- AC-07-07 (deterministic part) -----------------------------------------------------------------------


def _faithful(messages: list[Any]) -> str:
    system = str(messages[0].content)
    if "<draft>" in system:
        return re.search(r"<draft>(.*)</draft>", system, re.DOTALL).group(1)  # type: ignore[union-attr]
    data = json.loads(re.search(r"<assessment>(.*)</assessment>", system, re.DOTALL).group(1))  # type: ignore[union-attr]
    lines = [f"- {f['message']} {f['citation']}" for f in data["findings"]]
    return "\n".join([f"Position. {data['label']}", *lines, *data["next_best_actions"]])


def _lazy(messages: list[Any]) -> str:
    return "The claim has some issues. [claims:CLM300210]"


@pytest.mark.integration
@pytest.mark.parametrize("narrator", [_faithful, _lazy], ids=["faithful", "lazy"])
@pytest.mark.parametrize("item", all_items(), ids=item_ids(all_items()))
def test_AC_07_07_must_mention_covered_with_scripted_narrative(
    warehouse_ready: None, monkeypatch: pytest.MonkeyPatch, item: dict[str, Any], narrator: Any
) -> None:
    install(monkeypatch, {"Text": narrator})
    ctx = ToolContext(persona="claims_agent", as_of="2026-10-01", trace_id="t-ac0707")  # type: ignore[arg-type]
    question = item["turns"][-1]["content"]
    result = analyze(ctx, item["labels"]["claim_id"], narrate=True, question=question)
    assert isinstance(result, ClaimAssessment) and result.narrative
    text = result.narrative.casefold()
    missed = [p for p in item["labels"]["must_mention"] if p.casefold() not in text]
    assert not missed, missed
    for r in result.rules:
        if r.status == "fail" and r.severity in ("blocker", "escalate"):
            assert r.message and r.message in result.narrative, r.id
    if item["id"] == "CA001":
        assert "₹58,119" in result.narrative


@pytest.mark.integration
@pytest.mark.parametrize("item", seed_items(), ids=item_ids(seed_items()))
def test_narrative_input_is_the_only_source_and_carries_every_label(
    warehouse_ready: None, item: dict[str, Any]
) -> None:
    a = _assessment(item["labels"]["claim_id"])
    data = narrative_input(a)
    labels = {f["citation"] for f in data["findings"]} | {data["label"]}
    assert labels <= {s.label for s in a.sources}
    assert "fraud_risk_score" not in json.dumps(data)  # the narrative never sees raw scores
