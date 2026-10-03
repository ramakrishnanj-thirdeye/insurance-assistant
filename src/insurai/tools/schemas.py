"""Types shared by every tool (spec 05, Common types)."""

from datetime import date
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field, SerializerFunctionWrapHandler, model_serializer

Persona = Literal["customer", "claims_agent", "supervisor"]


class ToolContext(BaseModel):
    persona: Persona
    principal_id: str | None = None  # customer_id for persona=customer
    as_of: date
    trace_id: str


class SourceRef(BaseModel):
    kind: Literal["sql", "policy", "config"]
    label: str  # "[claims:CLM300210]", "[Health Secure Plus §5 Maternity]"
    table: str | None = None
    key: str | None = None
    product: str | None = None
    section_no: int | None = None
    section_name: str | None = None


class NotFound(BaseModel):
    kind: Literal["not_found"] = "not_found"
    entity: str
    message: str


class AccessDenied(BaseModel):
    kind: Literal["access_denied"] = "access_denied"
    message: str


# Every tool returns   <ResultModel> | NotFound | AccessDenied
# and every ResultModel has sources: list[SourceRef] (≥ 1).


class ToolResult(BaseModel):
    """Base of every successful result. Fields named in MASKABLE are left unset for personas that must
    not see them (config/personas.yaml hidden_columns) and are then absent from dict, JSON and MCP output.
    """

    MASKABLE: ClassVar[frozenset[str]] = frozenset()

    sources: list[SourceRef] = Field(min_length=1)

    @model_serializer(mode="wrap")
    def _drop_masked(self, handler: SerializerFunctionWrapHandler) -> Any:
        data = handler(self)
        for name in self.MASKABLE - self.model_fields_set:
            data.pop(name, None)
        return data


class HospitalSummary(BaseModel):
    hospital_id: str
    hospital_name: str
    city: str
    network_status: str
    specialty: str


class ClaimView(ToolResult):
    MASKABLE: ClassVar[frozenset[str]] = frozenset(
        {"customer_name", "fraud_risk_score", "manual_review_flag", "risk_segment"}
    )

    claim_id: str
    customer_id: str
    customer_name: str | None = None
    policy_id: str
    policy_type: str
    product_name: str
    claim_date: date
    claim_amount: int
    claim_status: str
    approved_amount: int | None
    diagnosis_or_loss_type: str
    rejection_or_adjustment_reason: str | None
    # policy period and schedule
    policy_start_date: date
    policy_end_date: date
    policy_status: str
    effective_status: str
    sum_insured: int
    co_pay_pct: int
    deductible: int
    waiting_period_days: int
    continuous_cover_start: date | None
    # derived flags (spec 01)
    in_policy_period: bool
    days_since_policy_start: int | None
    days_since_cover_start: int | None
    within_schedule_waiting: bool | None
    expected_payable: int | None
    high_value: bool
    coverage_status: str | None
    coverage_section: int | None
    coverage_reason: str | None
    required_waiting_days: int | None
    waiting_basis: str | None
    waiting_reason: str | None
    kyc_status: str | None
    docs_required: int
    docs_required_missing: int
    docs_required_pending: int
    docs_required_rejected: int
    hospital: HospitalSummary | None
    # hidden from the customer persona
    fraud_risk_score: float | None = None
    manual_review_flag: int | None = None
    risk_segment: str | None = None


class DocRow(BaseModel):
    document_type: str
    required: bool
    checklist_status: str  # No record | Missing | Verified | Pending verification | Rejected
    upload_status: str | None
    verification_status: str | None
    file_type: str | None


class DocumentChecklist(ToolResult):
    claim_id: str
    policy_type: str
    rows: list[DocRow]
    missing: list[str]  # required and No record or Missing
    pending: list[str]
    rejected: list[str]
    untracked: list[str]  # required by the wordings but not tracked in the system; never "missing"
    counts: dict[str, int]  # rows per checklist_status


class PolicyView(ToolResult):
    policy_id: str
    customer_id: str
    policy_type: str
    product_name: str
    policy_start_date: date
    policy_end_date: date
    sum_insured: int
    annual_premium: int
    policy_status: str  # as recorded; stale for many rows
    effective_status: str  # use this one
    status_conflict: bool
    days_to_expiry: int
    co_pay_pct: int
    deductible: int
    waiting_period_days: int
    continuous_cover_start: date | None


class CustomerSummary(ToolResult):
    MASKABLE: ClassVar[frozenset[str]] = frozenset({"customer_name", "risk_segment"})

    customer_id: str
    customer_name: str | None = None
    age: int | None
    gender: str | None
    city: str | None
    state: str | None
    customer_since: date | None
    kyc_status: str | None
    policies_total: int
    policies_in_force: int
    claims_total: int
    claims_open: int
    risk_segment: str | None = None


class Match(BaseModel):
    id: str
    city: str | None = None
    age: int | None = None
    policies: int | None = None
    specialty: str | None = None


class Disambiguation(ToolResult):
    kind: Literal["disambiguation"] = "disambiguation"
    entity: Literal["customer", "hospital"]
    total_matches: int
    matches: list[Match]  # at most 10
    message: str


class HospitalCheck(ToolResult):
    hospital_id: str
    hospital_name: str
    city: str
    network_status: str
    specialty: str
    alternatives: list[HospitalSummary]  # Network, same city and specialty, never the hospital itself


class InteractionRow(BaseModel):
    interaction_id: str
    interaction_date: date
    channel: str
    intent: str
    sentiment: str
    resolution_status: str
    before_claim_date: bool


class InteractionHistory(ToolResult):
    claim_id: str
    rows: list[InteractionRow]  # newest first
    total: int
    counts_by_intent: dict[str, int]
    latest_intent: str | None
    latest_sentiment: str | None
    open_escalations: int
    before_claim_date_count: int
