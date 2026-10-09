"""Guardrail models (spec 08 Interfaces)."""

from typing import Literal

from pydantic import BaseModel, Field

RefusalCode = Literal[
    "ACCESS_DENIED", "OUT_OF_SCOPE", "INJECTION", "GUARANTEE_REQUEST", "NOT_FOUND", "LOW_CONFIDENCE"
]


class GuardResult(BaseModel):
    allowed: bool
    code: RefusalCode | None = None
    masked_text: str
    pii_found: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    guarantee_request: bool = (
        False  # answered from the wording with the §15 citation, never refused (spec 08)
    )


class CheckOutcome(BaseModel):
    check: str  # V1..V7
    passed: bool
    detail: str = ""
    skipped: bool = False  # V7 when it did not run (v7_live off, judge error); passed is then True


class GroundedClaim(BaseModel):
    text: str
    supported: bool
    evidence_label: str | None = None


class GroundednessVerdict(BaseModel):
    """V7 judge output (verify_groundedness.md)."""

    claims: list[GroundedClaim] = Field(default_factory=list)
    conflict_rule_followed: bool | None = None


class HiddenValues(BaseModel):
    """V6: the customer's hidden values for this turn (fraud scores as V3 tokens, risk segments)."""

    fraud_scores: set[str] = Field(default_factory=set)
    segments: set[str] = Field(default_factory=set)


class VerificationReport(BaseModel):
    passed: bool
    checks: list[CheckOutcome]
    orphan_numbers: list[str] = Field(default_factory=list)
    invalid_citations: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    feedback: str = ""  # fed back to synthesize on retry
