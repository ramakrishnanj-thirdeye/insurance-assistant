"""Semantic layer models (spec 02). Only what spec 04 needs exists so far."""

from pydantic import BaseModel, ConfigDict


class VerifiedQuery(BaseModel):
    """A tested question → SQL pair; seeds the sql_examples collection (spec 04)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    question: str
    sql: str
