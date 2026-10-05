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


class CheckOutcome(BaseModel):
    check: str  # V1..V7
    passed: bool
    detail: str = ""


class VerificationReport(BaseModel):
    passed: bool
    checks: list[CheckOutcome]
    orphan_numbers: list[str] = Field(default_factory=list)
    invalid_citations: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    feedback: str = ""  # fed back to synthesize on retry
