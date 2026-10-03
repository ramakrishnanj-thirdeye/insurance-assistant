"""Unit checks for the tool layer: ID formats, persona config, source labels, masking, tracing."""

from datetime import date
from typing import Any

import pytest
from insurai.tools.claims import get_claim

from insurai import db
from insurai.tools import access, ids, sources
from insurai.tools.schemas import AccessDenied, ClaimView, NotFound, SourceRef, ToolContext

pytestmark = pytest.mark.unit

HIDDEN = ("fraud_risk_score", "manual_review_flag", "risk_segment", "customer_name")


def _ctx(persona: Any = "claims_agent", principal_id: str | None = None) -> ToolContext:
    return ToolContext(persona=persona, principal_id=principal_id, as_of=date(2026, 10, 1), trace_id="t")


@pytest.mark.parametrize(
    ("kind", "good", "bad"),
    [
        ("claim", "CLM300210", "CLM30021"),
        ("policy", "POL218917", "POL-218917"),
        ("customer", "CUST139920", "cust139920x"),
        ("hospital", "HOSP1257", "HOSP12570"),
    ],
)
def test_AC_05_01_id_formats_validated(kind: ids.IdKind, good: str, bad: str) -> None:
    assert ids.validate_id(kind, good) is None
    result = ids.validate_id(kind, bad)
    assert isinstance(result, NotFound) and result.entity == kind
    assert ids.EXAMPLES[kind] in result.message  # the hint shows the expected format


def test_AC_05_01_bad_id_rejected_before_any_query(monkeypatch: pytest.MonkeyPatch) -> None:
    def _no_db(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("queried the warehouse with a malformed ID")

    monkeypatch.setattr(db, "connect", _no_db)
    assert isinstance(get_claim(_ctx(), "CLM'; DROP TABLE x;--"), NotFound)


def test_AC_05_01_tool_not_listed_for_persona_denied() -> None:
    personas = access.load_personas()
    assert "run_analytics" not in personas["customer"].tools
    assert not access.tool_allowed(_ctx("customer", "CUST139920"), "run_analytics")
    assert access.tool_allowed(_ctx("supervisor"), "portfolio_audit")


def test_AC_05_01_customer_without_principal_owns_nothing() -> None:
    assert not access.can_see_owner(_ctx("customer", None), "CUST139920")
    assert access.can_see_owner(_ctx("customer", "CUST139920"), "CUST139920")
    assert access.can_see_owner(_ctx("claims_agent"), "CUST139920")


def test_AC_05_03_label_regexes_from_guardrails() -> None:
    sql_re, policy_re = sources.label_regexes()
    labels = [
        "[claims:CLM300210]",
        "[policies:POL218917]",
        "[claim_documents:CLM300210]",
        "[hospitals:HOSP1257]",
        "[interactions:CLM300210]",
        "[customers:CUST139920]",
    ]
    for label in labels:
        assert sql_re.fullmatch(label), label
    assert policy_re.fullmatch("[Health Secure Plus §5 Maternity]")
    assert not sql_re.fullmatch("[claims CLM300210]")
    assert not policy_re.fullmatch("[Health Secure Plus Maternity]")
    assert sources.sql_source("claims", "CLM300210").label == "[claims:CLM300210]"


def test_AC_05_04_hidden_columns_from_config() -> None:
    assert set(HIDDEN) <= access.hidden_columns(_ctx("customer", "CUST139920"))
    assert access.hidden_columns(_ctx("supervisor")) == frozenset()


def test_AC_05_04_masked_fields_absent_from_dump_and_json() -> None:
    row = _claim_row()
    src = [sources.sql_source("claims", "CLM300210")]
    view = ClaimView.model_validate({**access.visible(_ctx("customer", "CUST139920"), row), "sources": src})
    dumped, as_json = view.model_dump(), view.model_dump_json()
    for name in HIDDEN:
        assert name not in dumped and name not in as_json
    full = ClaimView.model_validate({**row, "sources": src})
    assert full.model_dump()["fraud_risk_score"] == 0.42


def test_M3_error_results_use_guardrails_refusal_texts() -> None:
    assert access.denied() == AccessDenied(
        message="I can only share details of policies and claims linked to your own account."
    )
    assert "CLM999999" in ids.not_found("claim", "CLM999999").message


def test_M3_source_ref_kind_sql() -> None:
    ref = sources.sql_source("hospitals", "HOSP1257")
    assert ref == SourceRef(kind="sql", label="[hospitals:HOSP1257]", table="hospitals", key="HOSP1257")


def test_M3_tool_calls_traced_with_name_and_args_without_pii(monkeypatch: pytest.MonkeyPatch) -> None:
    from insurai.tools.customers import get_customer_summary
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from insurai.observability import tracing

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(tracing, "_tracer", lambda: provider.get_tracer("test"))

    # a customer may not search by name: denied before any query, and still traced
    result = get_customer_summary(_ctx("customer", "CUST139920"), name="Arjun Sharma")
    assert isinstance(result, AccessDenied)
    (span,) = exporter.get_finished_spans()
    attrs = dict(span.attributes or {})
    assert span.name == "tool.get_customer_summary"
    assert "Arjun" not in str(attrs)
    assert attrs["tool.result_kind"] == "access_denied"
    assert attrs["tool.duration_ms"] >= 0 and attrs["tool.result_size"] > 0


def _claim_row() -> dict[str, Any]:
    return {
        "claim_id": "CLM300210",
        "customer_id": "CUST139920",
        "customer_name": "A Name",
        "policy_id": "POL218917",
        "policy_type": "Health",
        "product_name": "Health Secure Plus",
        "claim_date": date(2025, 1, 1),
        "claim_amount": 100,
        "claim_status": "Approved",
        "approved_amount": 90,
        "diagnosis_or_loss_type": "Fracture",
        "rejection_or_adjustment_reason": None,
        "policy_start_date": date(2024, 6, 1),
        "policy_end_date": date(2025, 5, 31),
        "policy_status": "Active",
        "effective_status": "Lapsed",
        "sum_insured": 500000,
        "co_pay_pct": 0,
        "deductible": 0,
        "waiting_period_days": 30,
        "continuous_cover_start": date(2024, 6, 1),
        "in_policy_period": True,
        "days_since_policy_start": 214,
        "days_since_cover_start": 214,
        "within_schedule_waiting": False,
        "expected_payable": 100,
        "high_value": False,
        "coverage_status": "Covered",
        "coverage_section": 3,
        "coverage_reason": None,
        "required_waiting_days": 30,
        "waiting_basis": None,
        "waiting_reason": None,
        "kyc_status": "Verified",
        "docs_required": 6,
        "docs_required_missing": 0,
        "docs_required_pending": 0,
        "docs_required_rejected": 0,
        "hospital": None,
        "fraud_risk_score": 0.42,
        "manual_review_flag": 0,
        "risk_segment": "Low",
    }
