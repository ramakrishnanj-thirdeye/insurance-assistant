"""Claim Dossier and Eval Dashboard pages driven by AppTest with a fake API client (spec 10)."""

from typing import Any

import pytest
from streamlit.testing.v1 import AppTest
from views import page_keys

from insurai.api.client import Identity

pytestmark = pytest.mark.unit

DOSSIER = {
    "claim_id": "CLM300210",
    "view": "full",
    "facts": {
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
    },
    "rules": [
        {
            "id": "R01",
            "name": "Policy in force on claim date",
            "status": "fail",
            "severity": "blocker",
            "message": "The claim date falls outside the policy period.",
            "citation": {"label": "[policies:POL218917]"},
        },
        {
            "id": "R05",
            "name": "Network hospital",
            "status": "pass",
            "severity": "info",
            "message": None,
            "citation": None,
        },
    ],
    "checklist": {
        "rows": [{"document_type": "Claim Form", "required": True, "checklist_status": "No record"}],
        "missing": ["Claim Form"],
        "pending": ["Hospital Bill"],
        "rejected": [],
        "untracked": [],
    },
    "interactions": {
        "rows": [
            {
                "interaction_date": "2025-03-10",
                "channel": "Phone",
                "intent": "Status",
                "sentiment": "Neutral",
                "resolution_status": "Resolved",
                "before_claim_date": False,
            }
        ]
    },
    "next_best_actions": ["Request Claim Form from the customer"],
    "consistency": [{"id": "C1", "name": "Paid despite blockers"}],
    "needs_human_review": True,
    "escalation_reasons": [],
    "narrative": None,
    "clauses": [],
    "customer_message_draft": None,
}
NARRATED = DOSSIER | {
    "narrative": "Claim CLM300210 is Approved but falls outside the policy period. [policies:POL218917]",
    "clauses": [
        {
            "chunk": {
                "citation_label": "[Critical Care Elite §4 Coverage]",
                "text": "Listed illnesses only.",
            },
            "via": "pinned",
        }
    ],
    "customer_message_draft": "Dear customer, we need your claim form.",
}
REPORT = {
    "suite": "slice-claim_analysis",
    "profile": "local",
    "coverage_status": "reviewed",
    "gate": [],
    "advisory": ["claim_analysis.correctness"],
    "open_gates": [
        {
            "metric": "claim_analysis.correctness",
            "value": 0.5,
            "target": "min 0.9",
            "counts": [5, 10],
            "advisory": True,
        }
    ],
    "calibration": {
        "part_a": {
            "status": "scored",
            "counts": [6, 10],
            "items": 10,
            "human_scored": 10,
            "rows": [{"id": "CAL01", "item": "x", "human": 4, "judge": 5, "agree": True}],
        },
        "part_b": {"status": "scored", "counts": [3, 7], "sampled": 7, "total": 7, "rows": []},
        "uncalibrated": True,
    },
    "slices": {
        "claim_analysis": {
            "metrics": {"correctness": 0.5, "wrong": ["CA001"]},
            "counts": {"correctness": [5, 10]},
            "items": [{"id": "CA001", "narrative": "…", "judge_reason": "misses review"}],
        }
    },
    "questions": {"CA001": "Analyze claim CLM300101"},
}
ABLATION = {
    "suite": "ablation",
    "configs": {
        "A": {"description": "dense-only", "metrics": {"recall_at_5": 1.0, "product_precision_at_5": 0.69}}
    },
}
SUMMARIES = [
    {
        "run_id": "slice-claim_analysis_20261010T011212Z",
        "suite": "slice-claim_analysis",
        "created_at": "2026-10-10T01:12:12+00:00",
        "git_sha": "abc",
        "headline": {},
    },
    {
        "run_id": "ablation_20261003T213134Z",
        "suite": "ablation",
        "created_at": "2026-10-03T21:31:34+00:00",
        "git_sha": "def",
        "headline": {"A": {"recall_at_5": 1.0}},
    },
]


class FakeApi:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def health(self) -> dict[str, Any]:
        return {"status": "ok", "llm_profile": "local", "as_of": "2026-10-01", "coverage_status": "reviewed"}

    def list_threads(self, ident: Identity, limit: int = 20) -> list[dict[str, Any]]:
        return []

    def dossier(self, claim_id: str, ident: Identity, narrate: bool = False) -> dict[str, Any]:
        self.calls.append(("dossier", claim_id, ident.persona, narrate))
        return NARRATED if narrate else DOSSIER

    def eval_reports(self, ident: Identity) -> list[dict[str, Any]]:
        return SUMMARIES

    def eval_report(self, run_id: str, ident: Identity) -> dict[str, Any]:
        self.calls.append(("eval_report", run_id))
        return ABLATION if run_id.startswith("ablation") else REPORT


def _page(module: str, fake: FakeApi, **query: str) -> AppTest:
    script = f"import sidebar, state, {module}\nstate.api()\nsidebar.render()\n{module}.render()\n"
    at = AppTest.from_string(script, default_timeout=30)
    at.session_state["api"] = fake
    for key, value in query.items():
        at.query_params[key] = value
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _md(at: AppTest) -> str:
    return "\n".join(m.value for m in at.markdown)


def test_AC_10_10_dossier_page_header_rules_documents_actions_and_flags() -> None:
    fake = FakeApi()
    at = _page("dossier_page", fake, persona="supervisor", claim="CLM300210")
    assert fake.calls == [("dossier", "CLM300210", "supervisor", False)]
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Approved"] == "₹64,577" and metrics["Expected payable"] == "₹58,119"
    assert any("₹6,458 above the expected payable" in w.value for w in at.warning)
    text = _md(at)
    assert ":red-badge[fail · blocker] **R01 Policy in force on claim date**" in text
    assert ":green-badge[pass]" in text and "[policies:POL218917]" in text
    assert "**Untracked documents:** none" in text and "**Missing:** Claim Form" in text
    assert "Request Claim Form from the customer" in text
    assert "Consistency flags" in text and "Paid despite blockers" in text
    assert len(at.dataframe) == 2  # documents and the interactions timeline


def test_AC_10_10_claims_agent_does_not_see_consistency_flags() -> None:
    at = _page("dossier_page", FakeApi(), persona="claims_agent", claim="CLM300210")
    assert "Consistency flags" not in _md(at) and "Paid despite blockers" not in _md(at)


def test_AC_10_10_add_narrative_loads_clauses_and_customer_draft() -> None:
    fake = FakeApi()
    at = _page("dossier_page", fake, persona="claims_agent", claim="CLM300210")
    at.button(key="dossier-narrate").click().run()
    assert ("dossier", "CLM300210", "claims_agent", True) in fake.calls
    assert "falls outside the policy period" in _md(at)
    assert [e.label for e in at.expander] == ["[Critical Care Elite §4 Coverage]"]
    assert at.code[0].value == "Dear customer, we need your claim form."


def test_AC_10_11_eval_dashboard_sections() -> None:
    fake = FakeApi()
    at = _page("eval_page", fake, persona="claims_agent")
    assert at.selectbox(key="eval-run").value == 0  # the newest non-ablation run
    text = _md(at)
    assert "Judge agreement" in text and "judge uncalibrated" in text
    assert "Part A" in text and "Part B" in text
    assert ("eval_report", "ablation_20261003T213134Z") in fake.calls  # the ablation chart's data
    assert [h.value for h in at.main.subheader] == [
        "Metrics against targets",
        "Judge calibration",
        "Retrieval ablation",
        "Metric history",
        "Failed items",
    ]
    failed = at.dataframe[-1].value
    assert list(failed["id"]) == ["CA001"] and list(failed["question"]) == ["Analyze claim CLM300101"]


@pytest.mark.parametrize(
    ("persona", "keys"),
    [
        ("customer", ["chat"]),
        ("claims_agent", ["chat", "dossier", "eval"]),
        ("supervisor", ["chat", "dossier", "eval"]),
    ],
)
def test_AC_10_10_pages_per_persona(persona: str, keys: list[str]) -> None:
    assert page_keys(persona) == keys
