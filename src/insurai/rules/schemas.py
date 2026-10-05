"""Claim-judgment models (spec 07 Interfaces). Defined in M4 so the agent graph (spec 06) can carry them;
the rules engine fills them in M5.
"""

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
