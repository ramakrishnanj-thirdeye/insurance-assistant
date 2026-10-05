"""Caller identity from headers (spec 09): X-Persona (required) and X-Principal-Id (required for customer;
an operator name for staff personas, default `staff`). PoC only; production maps SSO claims to the same two.
"""

from typing import Annotated, get_args

from fastapi import Header
from pydantic import BaseModel

from insurai.api.problems import ApiError
from insurai.tools.schemas import Persona

STAFF_DEFAULT = "staff"
PERSONAS: tuple[str, ...] = get_args(Persona)


class Identity(BaseModel):
    persona: Persona
    principal_id: str

    @property
    def tool_principal(self) -> str | None:
        """principal_id for ToolContext and the graph: the customer_id for customers, None for staff."""
        return self.principal_id if self.persona == "customer" else None


def identity(
    x_persona: Annotated[str | None, Header()] = None,
    x_principal_id: Annotated[str | None, Header()] = None,
) -> Identity:
    if x_persona not in PERSONAS:
        raise ApiError(400, "IDENTITY_REQUIRED", f"X-Persona must be one of {list(PERSONAS)}.")
    principal = (x_principal_id or "").strip()
    if x_persona == "customer" and not principal:
        raise ApiError(400, "IDENTITY_REQUIRED", "X-Principal-Id (the customer ID) is required for customer.")
    return Identity(persona=x_persona, principal_id=principal or STAFF_DEFAULT)  # type: ignore[arg-type]


def ensure_matches(ident: Identity, persona: str | None, principal_id: str | None) -> None:
    """Body or query identity is optional; when present it must equal the headers."""
    if persona is not None and persona != ident.persona:
        raise ApiError(400, "IDENTITY_MISMATCH", "persona differs from X-Persona.")
    if principal_id is not None and principal_id != ident.principal_id:
        raise ApiError(400, "IDENTITY_MISMATCH", "principal_id differs from X-Principal-Id.")
