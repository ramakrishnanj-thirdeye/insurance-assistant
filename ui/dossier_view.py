"""Pure helpers for the Claim Dossier page (spec 10, AC-10-10): header, rule badges, documents, timeline.

Severity colours (spec 10): blocker red, warning amber, escalate purple, info grey, pass green. Streamlit's
markdown badges carry the colour; the page never computes a value, it only formats what the API returned.
"""

from typing import Any

from insurai.formatting import inr

SEVERITY_COLOUR = {"blocker": "red", "warning": "orange", "escalate": "violet", "info": "gray"}
STATUS_TEXT = {"pass": "pass", "fail": "fail", "review": "review", "not_applicable": "n/a"}
STAFF = ("claims_agent", "supervisor")
CONSISTENCY_PERSONAS = ("supervisor",)  # consistency flags are a supervisor view (decided 2026-10-10)


def badge(colour: str, text: str) -> str:
    return f":{colour}-badge[{text}]"


def rule_badge(status: str, severity: str) -> str:
    """Pass green, n/a grey; a failed or review rule takes its severity's colour."""
    if status == "pass":
        return badge("green", "pass")
    if status == "not_applicable":
        return badge("gray", "n/a")
    return badge(SEVERITY_COLOUR.get(severity, "gray"), f"{STATUS_TEXT.get(status, status)} · {severity}")


def _money(value: Any) -> str:
    return inr(value) if isinstance(value, int | float) and not isinstance(value, bool) else "—"


def header_fields(facts: dict[str, Any]) -> list[tuple[str, str]]:
    """Label/value pairs for the header. The approved amount sits next to the expected payable, so a co-pay
    that was not applied shows at a glance (CLM300210: ₹64,577 approved against ₹58,119 payable)."""
    period = (
        f"{facts['policy_start_date']} to {facts['policy_end_date']}"
        if facts.get("policy_start_date") and facts.get("policy_end_date")
        else "—"
    )
    effective = facts.get("effective_status") or "—"
    if facts.get("policy_status") and facts.get("policy_status") != facts.get("effective_status"):
        effective += f" (recorded {facts['policy_status']})"
    return [
        ("Claim status", str(facts.get("claim_status") or "—")),
        ("Product", f"{facts.get('product_name') or '—'} ({facts.get('policy_type') or '—'})"),
        ("Claim date", str(facts.get("claim_date") or "—")),
        ("Policy period", period),
        ("Policy status", effective),
        ("Claimed", _money(facts.get("claim_amount"))),
        ("Approved", _money(facts.get("approved_amount"))),
        ("Expected payable", _money(facts.get("expected_payable"))),
    ]


def payable_gap(facts: dict[str, Any]) -> str | None:
    """A note when the approved amount exceeds the expected payable (co-pay or deductible not applied)."""
    approved, payable = facts.get("approved_amount"), facts.get("expected_payable")
    if not isinstance(approved, int | float) or not isinstance(payable, int | float) or approved <= payable:
        return None
    terms = []
    if facts.get("co_pay_pct"):
        terms.append(f"co-pay {facts['co_pay_pct']}%")
    if facts.get("deductible"):
        terms.append(f"deductible {_money(facts['deductible'])}")
    basis = f" ({', '.join(terms)})" if terms else ""
    return f"Approved {_money(approved)} is {_money(approved - payable)} above the expected payable{basis}."


def rule_rows(rules: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "badge": rule_badge(str(r.get("status")), str(r.get("severity"))),
            "rule": f"{r.get('id')} {r.get('name')}",
            "message": r.get("message") or "",
            "citation": (r.get("citation") or {}).get("label", ""),
        }
        for r in rules
    ]


def document_rows(checklist: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "document": r.get("document_type"),
            "required": "yes" if r.get("required") else "no",
            "status": r.get("checklist_status"),
            "upload": r.get("upload_status") or "—",
            "verification": r.get("verification_status") or "—",
        }
        for r in checklist.get("rows", [])
    ]


def timeline_rows(interactions: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Oldest first, so the timeline reads in order; the API returns newest first."""
    rows = list((interactions or {}).get("rows", []))
    return [
        {
            "date": r.get("interaction_date"),
            "channel": r.get("channel"),
            "intent": r.get("intent"),
            "sentiment": r.get("sentiment"),
            "resolution": r.get("resolution_status"),
            "before claim date": "yes" if r.get("before_claim_date") else "",
        }
        for r in sorted(rows, key=lambda r: str(r.get("interaction_date")))
    ]


def clause_label(clause: dict[str, Any]) -> str:
    chunk = clause.get("chunk") or {}
    return str(chunk.get("citation_label") or chunk.get("header") or chunk.get("chunk_id") or "clause")


def shows_consistency(persona: str) -> bool:
    return persona in CONSISTENCY_PERSONAS
