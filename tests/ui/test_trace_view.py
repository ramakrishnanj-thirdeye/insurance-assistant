"""Client-friendly trace view (spec 10, AC-10-12): plain steps, named checks, who answered. Pure helpers."""

from typing import Any

import pytest
from trace_view import (
    NO_LLM,
    answered_by_label,
    check_name,
    check_rows,
    chunk_rows,
    llm_rows,
    rule_rows,
    sql_blocks,
    step_rows,
)

from insurai.agent.graph import V7_OFF_NOTE

pytestmark = pytest.mark.unit

CUSTOMER_NAME = "Aditya Joshi"


def _ev(kind: str, name: str, start: float = 0, end: float = 0, **data: Any) -> dict[str, Any]:
    return {"kind": kind, "name": name, "turn": 1, "start_ms": start, "end_ms": end, "data": data}


CHECKS = [
    {"check": "V1", "passed": True, "detail": "", "skipped": False},
    {"check": "V3", "passed": False, "detail": "orphan numbers: 12,345", "skipped": False},
    {"check": "CURRENCY", "passed": True, "detail": "", "skipped": False},
    {"check": "V7", "passed": True, "detail": V7_OFF_NOTE.format(profile="local"), "skipped": True},
]
TRACE = [
    _ev("node", "input_guard", 0, 2, allowed=True, code=None, pii_found=[]),
    _ev("entity", "resolve_context", 2, 3, resolved=["claim_id"], fast_path=False),
    _ev("intent", "plan", 3, 3, intents=["claim_analysis", "policy_question"]),
    _ev(
        "llm",
        "planner",
        3,
        900,
        role="generator",
        model="qwen3:8b",
        prompt_id="planner",
        prompt_version="0.3.0",
        input_tokens=1200,
        output_tokens=80,
        latency_ms=897.0,
    ),
    _ev("prompt", "planner", 900, 900, prompt_id="planner", version="0.3.0"),
    _ev(
        "tool", "get_claim", 900, 935, args={"claim_id": "CLM300210", "name": CUSTOMER_NAME}, result_kind="ok"
    ),
    _ev("tool", "search_policy", 940, 1100, args={"query": CUSTOMER_NAME, "product": "Health Secure Plus"}),
    _ev(
        "retrieval",
        "search_policy",
        940,
        1100,
        confident=True,
        chunks=[
            {
                "label": "[Health Secure Plus §5 Maternity]",
                "fused_rank": 1,
                "rerank_score": 3.2,
                "via": "search",
            }
        ],
    ),
    _ev("rule", "R01", 1100, 1100, status="fail", severity="blocker"),
    _ev("node", "evaluate_rules", 1100, 1180, rules=12),
    _ev("tool", "run_analytics", 1180, 1200, sql="SELECT 1"),
    _ev("verify", "verify", 1200, 1210, outcome="retry", checks=CHECKS[:1]),
    _ev("verify", "verify", 1300, 1310, outcome="pass", checks=CHECKS),
    _ev("total", "turn", 0, 1320, answered_by="draft", llm_written=True),
]


def test_AC_10_12_plain_steps_in_order_with_times_and_no_customer_name() -> None:
    steps = step_rows(TRACE)
    labels = [s["step"] for s in steps]
    assert labels[:3] == [
        "Checked the question for safety",
        "Found the claim, policy and product references",
        "Understood the question: claim analysis + policy question",
    ]
    assert "Language model planned which records to check" in labels
    assert "Looked up claim CLM300210" in labels and "Searched the Health Secure Plus wording" in labels
    assert "Ranked 1 policy clauses" in labels and "Checked the claim against 12 rules" in labels
    assert labels.count("Checked the answer before showing it") == 2
    assert next(s for s in steps if s["step"].startswith("Looked up claim"))["ms"] == 35.0
    assert all(CUSTOMER_NAME not in str(s) for s in steps)
    assert not any("prompt" in s["step"].lower() for s in steps)  # prompt events stay in engineer details


def test_AC_10_12_named_checks_detail_on_failure_and_v7_skipped_eval_only() -> None:
    rows = check_rows(TRACE)  # the last verify attempt
    assert [r["check"] for r in rows] == [
        "V1 Citations are real",
        "V3 Numbers traced to data",
        "CURRENCY Amounts in rupees",
        "V7 Grounded",
    ]
    assert rows[0] == {"check": "V1 Citations are real", "result": "✓ passed", "detail": ""}
    assert rows[1]["result"] == "✗ failed" and rows[1]["detail"] == "orphan numbers: 12,345"
    assert rows[3]["result"] == "skipped (eval only)" and rows[3]["detail"] == ""


@pytest.mark.parametrize(
    ("check", "name"),
    [
        ("V1", "Citations are real"),
        ("V2", "Facts are cited"),
        ("V3", "Numbers traced to data"),
        ("V4", "No promises"),
        ("V5", "No personal data leaked"),
        ("V6", "Hidden fields protected"),
        ("V7", "Grounded"),
    ],
)
def test_AC_10_12_every_check_has_its_plain_name(check: str, name: str) -> None:
    assert check_name(check) == f"{check} {name}"


@pytest.mark.parametrize(
    ("data", "label"),
    [
        ({"answered_by": "draft", "llm_written": True}, "language model"),
        ({"answered_by": "draft", "llm_written": False}, NO_LLM),
        ({"answered_by": "template", "llm_written": False}, NO_LLM),
        ({"answered_by": "draft"}, NO_LLM),  # an older trace without llm_written and no synthesize call
        ({"answered_by": "refusal", "llm_written": False}, "fixed refusal (no LLM)"),
        ({"answered_by": "guard:INJECTION", "llm_written": False}, "safety check (no LLM)"),
    ],
)
def test_AC_10_12_answered_by_label(data: dict[str, Any], label: str) -> None:
    assert answered_by_label([_ev("total", "turn", **data)]) == label


def test_AC_10_02_trace_fields_chunks_rules_sql_and_llm_calls() -> None:
    assert chunk_rows(TRACE) == [
        {"label": "[Health Secure Plus §5 Maternity]", "fused rank": 1, "rerank score": 3.2, "via": "search"}
    ]
    assert rule_rows(TRACE) == [{"rule": "R01", "status": "fail", "severity": "blocker"}]
    assert sql_blocks(TRACE) == [("run_analytics", "SELECT 1")]
    call = llm_rows(TRACE)[0]
    assert call["prompt"] == "planner" and call["version"] == "0.3.0" and call["tokens in"] == 1200
    assert call["latency ms"] == 897.0 and call["model"] == "qwen3:8b"
