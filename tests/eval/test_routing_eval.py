"""Routing slice scorer (AC-06-02) and the e2e sql_facts gold matcher, without an LLM."""

from datetime import date

import pytest

from insurai.agent.schemas import Entities, Intent, Plan
from insurai.eval.e2e_sql_facts import gold_in_answer
from insurai.eval.routing import load_items, predicted, score_item

pytestmark = pytest.mark.unit


def test_AC_06_02_routing_metrics_set_equality_and_entity_exact() -> None:
    plan = Plan(
        intents=[
            Intent(
                id="i1", type="claim_documents", entities=Entities(claim_id="CLM300210"), sub_question="q"
            ),
            Intent(id="i2", type="claim_analysis", entities=Entities(claim_id="CLM300210"), sub_question="q"),
        ]
    )
    route, entities = predicted(plan)
    assert score_item(["claim_analysis", "claim_documents"], {"claim_id": "CLM300210"}, route, entities) == (
        True,
        True,
    )
    assert score_item(["claim_analysis"], {"claim_id": "CLM300210"}, route, entities) == (False, True)
    assert score_item(["claim_analysis", "claim_documents"], {"claim_id": "CLM300500"}, route, entities) == (
        True,
        False,
    )
    assert score_item(["policy_question"], {}, [], {}) == (False, True)  # a clarification is a routing miss
    assert predicted(None) == ([], {})


def test_routing_items_cover_every_golden_slice_once() -> None:
    items = load_items()
    assert len({i.id for i in items}) == len(items)
    assert {i.slice for i in items} >= {"sql_facts", "policy_clauses", "claim_analysis", "multi_turn"}
    multi = [i for i in items if i.slice == "multi_turn"]
    assert len(multi) == 10 and all(len(i.turns) >= 2 for i in multi)


@pytest.mark.parametrize(
    ("gold", "answer", "hit"),
    [
        (64577, "Approved ₹64,577 on the claim. [claims:CLM300210]", True),
        (500000, "Sum insured is ₹5,00,000.", True),
        (60000, "Sum insured is ₹5,00,000.", False),
        ("Under Review", "Claim CLM300500 is **under review**.", True),
        (["Claim Form", "ID Proof"], "Missing: claim form and ID Proof.", True),
        (["Claim Form", "ID Proof"], "Missing: claim form.", False),
        ([], "No documents are missing.", True),
        (date(2025, 3, 4), "Filed on 2025-03-04.", True),
        (None, "anything", None),
    ],
)
def test_e2e_sql_facts_gold_match_scorer(gold: object, answer: str, hit: bool | None) -> None:
    assert gold_in_answer(gold, answer) is hit
