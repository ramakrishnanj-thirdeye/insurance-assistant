"""Claim Dossier helpers (spec 10, AC-10-10): header in rupees, payable gap, severity badges, timeline."""

import pytest
from dossier_view import (
    header_fields,
    payable_gap,
    rule_badge,
    rule_rows,
    shows_consistency,
    timeline_rows,
)

pytestmark = pytest.mark.unit

FACTS = {  # CLM300210 as the API returns it
    "claim_status": "Approved",
    "product_name": "Critical Care Elite",
    "policy_type": "Health",
    "claim_date": "2025-03-04",
    "policy_start_date": "2023-06-14",
    "policy_end_date": "2024-06-13",
    "policy_status": "Active",
    "effective_status": "Lapsed",
    "claim_amount": 64577,
    "approved_amount": 64577,
    "expected_payable": 58119,
    "co_pay_pct": 10,
    "deductible": 0,
}


def test_AC_10_10_header_shows_approved_next_to_expected_payable_in_rupees() -> None:
    fields = dict(header_fields(FACTS))
    assert fields["Approved"] == "₹64,577" and fields["Expected payable"] == "₹58,119"
    assert fields["Policy status"] == "Lapsed (recorded Active)"
    assert fields["Policy period"] == "2023-06-14 to 2024-06-13"
    labels = [label for label, _ in header_fields(FACTS)]
    assert labels.index("Expected payable") == labels.index("Approved") + 1
    assert "Paid" not in fields  # the warehouse has no paid amount


def test_AC_10_10_payable_gap_makes_the_unapplied_copay_visible() -> None:
    assert payable_gap(FACTS) == "Approved ₹64,577 is ₹6,458 above the expected payable (co-pay 10%)."
    assert payable_gap(FACTS | {"approved_amount": 58119}) is None
    assert payable_gap(FACTS | {"approved_amount": None}) is None


@pytest.mark.parametrize(
    ("status", "severity", "colour"),
    [
        ("fail", "blocker", "red"),
        ("fail", "warning", "orange"),
        ("review", "escalate", "violet"),
        ("fail", "info", "gray"),
        ("pass", "blocker", "green"),
        ("not_applicable", "blocker", "gray"),
    ],
)
def test_AC_10_10_rule_badges_follow_the_severity_colours(status: str, severity: str, colour: str) -> None:
    assert rule_badge(status, severity).startswith(f":{colour}-badge[")


def test_AC_10_10_rule_rows_carry_message_and_citation() -> None:
    rule = {
        "id": "R01",
        "name": "Policy in force on claim date",
        "status": "fail",
        "severity": "blocker",
        "message": "The claim date 2025-03-04 falls outside the policy period.",
        "citation": {"label": "[policies:POL218917]"},
    }
    row = rule_rows([rule])[0]
    assert row["rule"] == "R01 Policy in force on claim date" and row["citation"] == "[policies:POL218917]"
    assert row["message"].startswith("The claim date")


def test_AC_10_10_timeline_reads_oldest_first() -> None:
    rows = [
        {
            "interaction_date": "2025-04-02",
            "channel": "Phone",
            "intent": "Status",
            "before_claim_date": False,
        },
        {"interaction_date": "2025-03-01", "channel": "Email", "intent": "Query", "before_claim_date": True},
    ]
    out = timeline_rows({"rows": rows})
    assert [r["date"] for r in out] == ["2025-03-01", "2025-04-02"] and out[0]["before claim date"] == "yes"
    assert timeline_rows(None) == []


def test_AC_10_10_consistency_flags_for_the_supervisor_only() -> None:
    assert shows_consistency("supervisor")
    assert not shows_consistency("claims_agent") and not shows_consistency("customer")
