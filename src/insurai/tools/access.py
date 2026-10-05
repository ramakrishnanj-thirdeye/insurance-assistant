"""Persona access control (config/personas.yaml), enforced in code before any data is returned.

Ownership is always the owning claim's or policy's customer_id; interactions are owned through their
claim (claim_owner_id), never logged_customer_id (ADR-008).
"""

from functools import lru_cache
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict

from insurai.settings import ROOT
from insurai.tools.messages import refusal
from insurai.tools.schemas import AccessDenied, Persona, ToolContext

PERSONAS_FILE = ROOT / "config" / "personas.yaml"


class PersonaConfig(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    row_scope: Literal["own_customer", "all"]
    hidden_columns: list[str]
    tools: list[str]
    can_resume_review: bool = False
    can_read_eval_reports: bool = False
    analyze_claim_view: Literal["full", "customer"] = "full"  # spec 07 Behaviour 8


@lru_cache(maxsize=1)
def load_personas() -> dict[Persona, PersonaConfig]:
    raw = yaml.safe_load(PERSONAS_FILE.read_text(encoding="utf-8"))
    return {name: PersonaConfig.model_validate(cfg) for name, cfg in raw["personas"].items()}


def tool_allowed(ctx: ToolContext, tool: str) -> bool:
    return tool in load_personas()[ctx.persona].tools


def hidden_columns(ctx: ToolContext) -> frozenset[str]:
    return frozenset(load_personas()[ctx.persona].hidden_columns)


def can_see_owner(ctx: ToolContext, owner_id: str | None) -> bool:
    """True when the persona may see a row owned by `owner_id`."""
    if load_personas()[ctx.persona].row_scope == "all":
        return True
    return ctx.principal_id is not None and owner_id == ctx.principal_id


def is_scoped(ctx: ToolContext) -> bool:
    """True for personas that only see their own rows (customer)."""
    return load_personas()[ctx.persona].row_scope == "own_customer"


def visible(ctx: ToolContext, row: dict[str, Any]) -> dict[str, Any]:
    """`row` without the persona's hidden columns."""
    hidden = hidden_columns(ctx)
    return {k: v for k, v in row.items() if k not in hidden}


def denied() -> AccessDenied:
    return AccessDenied(message=refusal("ACCESS_DENIED"))
