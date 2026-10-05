"""Claim-judgment models (spec 07 Interfaces), filled by the rules engine (insurai.rules.engine)."""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from insurai.retrieval.schemas import RetrievedChunk
from insurai.tools.schemas import DocumentChecklist, InteractionHistory, SourceRef

Severity = Literal["blocker", "escalate", "warning", "info"]  # config/rules.yaml


class RuleResult(BaseModel):
    id: str
    name: str
    status: Literal["pass", "fail", "review", "not_applicable"]
    severity: Severity
    message: str | None
    evidence: dict[str, Any]
    citation: SourceRef | None


class ConsistencyFlag(BaseModel):
    id: str  # C1..C4 (config/rules.yaml decision_consistency)
    name: str


class ReviewDecision(BaseModel):
    """The human reviewer's decision when the dossier pauses (spec 06, Memory, interrupts, streaming)."""

    action: Literal["approve", "override", "request_info"]
    note: str = ""


class ClaimAssessment(BaseModel):
    claim_id: str
    as_of: date
    view: Literal["full", "customer"]
    facts: dict[str, Any]
    rules: list[RuleResult] = Field(default_factory=list)
    checklist: DocumentChecklist
    consistency: list[ConsistencyFlag] = Field(default_factory=list)
    needs_human_review: bool
    escalation_reasons: list[str] = Field(default_factory=list)
    next_best_actions: list[str] = Field(default_factory=list)
    interactions: InteractionHistory | None = None
    clauses: list[RetrievedChunk] = Field(default_factory=list)
    narrative: str | None = None
    customer_message_draft: str | None = None
    review: ReviewDecision | None = None
    sources: list[SourceRef]


class PortfolioReport(BaseModel):
    """Counts over gold.rule_results (spec 07 `make rules`, spec 09 /audit/summary)."""

    as_of: date
    claims: int
    fail_counts: dict[str, int]  # rule id -> claims failing it
    review_counts: dict[str, int]
    consistency_counts: dict[str, int]  # C1..C4
    insight_counts: dict[str, int]  # P1..
    by_product: dict[str, dict[str, int]]  # product -> rule fails and consistency flags
    elapsed_ms: float | None = None
