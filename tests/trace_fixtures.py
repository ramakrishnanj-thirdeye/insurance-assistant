"""Trace events in the shapes the agent writes, shared by the UI and demo-check tests (AC-10-17)."""

from typing import Any

from insurai.agent.graph import intent_rows
from insurai.agent.schemas import Entities, Intent, Plan

POLICY_PLAN = Plan(
    intents=[
        Intent(
            id="i1",
            type="policy_question",
            entities=Entities(product="Health Secure Plus"),
            sub_question="What is the maternity waiting period under Health Secure Plus?",
        )
    ]
)
POLICY_TRACE: list[dict[str, Any]] = [  # the event shapes the agent writes on a planner turn
    {
        "kind": "intent",
        "name": "plan",
        "turn": 1,
        "start_ms": 1,
        "end_ms": 1,
        "data": {"raw": ["policy_question"], "intents": intent_rows(POLICY_PLAN), "clarification": None},
    },
    {
        "kind": "retrieval",
        "name": "policy_search",
        "turn": 1,
        "start_ms": 2,
        "end_ms": 40,
        "data": {
            "confident": True,
            "chunks": [
                {
                    "label": "[Health Secure Plus §5 Maternity]",
                    "fused_rank": 1,
                    "rerank_score": 0.91,
                    "via": "hybrid",
                }
            ],
        },
    },
    {
        "kind": "verify",
        "name": "verify",
        "turn": 1,
        "start_ms": 41,
        "end_ms": 42,
        "data": {
            "outcome": "pass",
            "checks": [{"check": "V1", "passed": True, "detail": "", "skipped": False}],
        },
    },
    {"kind": "total", "name": "turn", "data": {"answered_by": "draft", "llm_written": True}},
]
