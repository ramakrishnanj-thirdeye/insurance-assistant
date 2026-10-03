"""Types shared by every tool (spec 05, Common types)."""

from datetime import date
from typing import Literal

from pydantic import BaseModel

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
