"""Claim tools: get_claim, get_claim_documents, get_claim_interactions (spec 05)."""

from collections import Counter
from functools import lru_cache
from typing import Any

import yaml

from insurai.ingest.schemas import RequiredDocumentsConfig
from insurai.settings import ROOT
from insurai.tools import access
from insurai.tools.base import fetch_all, fetch_one, tool
from insurai.tools.ids import not_found, validate_id
from insurai.tools.schemas import (
    AccessDenied,
    ClaimView,
    DocRow,
    DocumentChecklist,
    HospitalSummary,
    InteractionHistory,
    InteractionRow,
    NotFound,
    ToolContext,
)
from insurai.tools.sources import sql_source

REQUIRED_DOCUMENTS_FILE = ROOT / "config" / "required_documents.yaml"
MISSING = ("No record", "Missing")
ESCALATED = "Escalated"

_CLAIM_FIELDS = frozenset(ClaimView.model_fields) - {"hospital", "sources"}


@tool
def get_claim(ctx: ToolContext, claim_id: str) -> ClaimView | NotFound | AccessDenied:
    """One claim: status and amounts, product, policy period, effective status, derived flags, hospital."""
    if bad := validate_id("claim", claim_id):
        return bad
    row = fetch_one("SELECT * FROM gold.v_claim_360 WHERE claim_id = ?", [claim_id])
    if row is None:
        return not_found("claim", claim_id)
    if not access.can_see_owner(ctx, row["customer_id"]):
        return access.denied()

    hospital = (
        HospitalSummary(
            hospital_id=row["hospital_id"],
            hospital_name=row["hospital_name"],
            city=row["hospital_city"],
            network_status=row["network_status"],
            specialty=row["hospital_specialty"],
        )
        if row["hospital_id"]
        else None
    )
    refs = [
        sql_source("claims", claim_id),
        sql_source("policies", row["policy_id"]),
        sql_source("customers", row["customer_id"]),
    ]
    if hospital:
        refs.append(sql_source("hospitals", hospital.hospital_id))
    fields = access.visible(ctx, {k: v for k, v in row.items() if k in _CLAIM_FIELDS})
    return ClaimView.model_validate({**fields, "hospital": hospital, "sources": refs})


@tool
def get_claim_documents(ctx: ToolContext, claim_id: str) -> DocumentChecklist | NotFound | AccessDenied:
    """Document checklist for a claim: required documents with their status, plus untracked requirements."""
    if bad := validate_id("claim", claim_id):
        return bad
    claim = _claim_owner(claim_id)
    if claim is None:
        return not_found("claim", claim_id)
    if not access.can_see_owner(ctx, claim["customer_id"]):
        return access.denied()

    rows = [
        DocRow.model_validate(r)
        for r in fetch_all(
            """SELECT document_type, required, checklist_status, upload_status, verification_status, file_type
               FROM gold.claim_doc_checklist WHERE claim_id = ?
               ORDER BY required DESC, document_type""",
            [claim_id],
        )
    ]
    required = [r for r in rows if r.required]
    return DocumentChecklist(
        claim_id=claim_id,
        policy_type=claim["policy_type"],
        rows=rows,
        missing=sorted(r.document_type for r in required if r.checklist_status in MISSING),
        pending=sorted(r.document_type for r in required if r.checklist_status == "Pending verification"),
        rejected=sorted(r.document_type for r in required if r.checklist_status == "Rejected"),
        untracked=_required_documents().policy_types[claim["policy_type"]].untracked,
        counts=dict(Counter(r.checklist_status for r in rows)),
        sources=[sql_source("claim_documents", claim_id)],
    )


@tool
def get_claim_interactions(ctx: ToolContext, claim_id: str) -> InteractionHistory | NotFound | AccessDenied:
    """Customer interactions about a claim, newest first. Owned via the claim, never the logged customer."""
    if bad := validate_id("claim", claim_id):
        return bad
    claim = _claim_owner(claim_id)
    if claim is None:
        return not_found("claim", claim_id)
    if not access.can_see_owner(ctx, claim["customer_id"]):
        return access.denied()

    rows = [
        InteractionRow.model_validate(r)
        for r in fetch_all(
            """SELECT interaction_id, interaction_date, channel, intent, sentiment, resolution_status,
                      before_claim_date
               FROM silver.customer_interactions WHERE claim_id = ?
               ORDER BY interaction_date DESC, interaction_id DESC""",
            [claim_id],
        )
    ]
    latest = rows[0] if rows else None
    return InteractionHistory(
        claim_id=claim_id,
        rows=rows,
        total=len(rows),
        counts_by_intent=dict(Counter(r.intent for r in rows)),
        latest_intent=latest.intent if latest else None,
        latest_sentiment=latest.sentiment if latest else None,
        open_escalations=sum(r.resolution_status == ESCALATED for r in rows),
        before_claim_date_count=sum(r.before_claim_date for r in rows),
        sources=[sql_source("interactions", claim_id)],
    )


def _claim_owner(claim_id: str) -> dict[str, Any] | None:
    return fetch_one("SELECT customer_id, policy_type FROM silver.claims WHERE claim_id = ?", [claim_id])


@lru_cache(maxsize=1)
def _required_documents() -> RequiredDocumentsConfig:
    return RequiredDocumentsConfig.model_validate(
        yaml.safe_load(REQUIRED_DOCUMENTS_FILE.read_text(encoding="utf-8"))
    )
