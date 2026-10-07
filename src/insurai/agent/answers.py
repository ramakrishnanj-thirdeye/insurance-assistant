"""Template answers (spec 06): a turn whose plan is one SQL-fact intent (claim_status, claim_documents,
hospital_check, policy_details) is answered from config/prompts/templates.md without a synthesize LLM call.

Templates read only the persona-filtered evidence payload: a field that is absent or None is never rendered.
When a field a template needs is missing, there is no template answer and the generator runs instead. Every
line is cited with a label from that evidence's sources. Verify still runs on the result.
"""

from typing import Any

from insurai.agent.prompts import template
from insurai.agent.schemas import AnswerDraft, Evidence, Plan
from insurai.formatting import inr
from insurai.guardrails.verify import labels_in
from insurai.rules.narrative import premise_correction

TEMPLATE_INTENTS = frozenset({"claim_status", "claim_documents", "hospital_check", "policy_details"})


class _Missing(Exception):
    """A field the template needs is absent from the persona-filtered payload."""


def template_draft(plan: Plan | None, evidence: list[Evidence], question: str) -> AnswerDraft | None:
    if plan is None or plan.clarification or len(plan.intents) != 1:
        return None
    intent = plan.intents[0]
    if intent.type not in TEMPLATE_INTENTS:
        return None
    mine = [ev for ev in evidence if ev.intent_id == intent.id]
    try:
        text = _RENDERERS[intent.type](mine, question)
    except _Missing:
        return None
    if not text:
        return None
    return AnswerDraft(answer_markdown=text, citations=list(dict.fromkeys(labels_in(text))))


def claim_status_text(ev: Evidence, question: str) -> str:
    """The claim_status answer (fast path and planner turns), led by a premise correction when the question
    assumes a status the claim does not have."""
    p = ev.payload
    label = _label(ev, "claims")
    claim_id, status = _need(p, "claim_id"), _need(p, "claim_status")
    approved = p.get("approved_amount")
    lines = [
        template(
            "claim_status",
            claim_id=claim_id,
            claim_status=status,
            approved_clause=f", with {inr(approved)} approved" if approved is not None else "",
            claim_date=_need(p, "claim_date"),
            claim_amount=inr(_need(p, "claim_amount")),
            product_name=_need(p, "product_name"),
            label=label,
        )
    ]
    if reason := p.get("rejection_or_adjustment_reason"):
        lines.append(template("claim_status_reason", reason=str(reason).rstrip("."), label=label))
    if correction := premise_correction(question, claim_id, status):
        lines.insert(0, correction)
    return "\n\n".join(lines)


def _claim_status(evidence: list[Evidence], question: str) -> str | None:
    ev = _one(evidence, "ClaimView")
    return claim_status_text(ev, question) if ev else None


def _claim_documents(evidence: list[Evidence], question: str) -> str | None:
    ev = _one(evidence, "DocumentChecklist")
    if ev is None:
        return None
    p, label = ev.payload, _label(ev, "claim_documents")
    claim_id = _need(p, "claim_id")
    missing = _need(p, "missing")
    if missing:
        lines = [
            template("claim_documents_missing", claim_id=claim_id, documents=_join(missing), label=label)
        ]
    else:
        lines = [template("claim_documents_none_missing", claim_id=claim_id, label=label)]
    for key, name in (("pending", "pending"), ("rejected", "rejected"), ("untracked", "untracked")):
        if docs := p.get(key):
            lines.append(template(f"claim_documents_{name}", documents=_join(docs), label=label))
    return "\n\n".join(lines)


def _hospital_check(evidence: list[Evidence], question: str) -> str | None:
    claim = _one(evidence, "ClaimView")
    hospital = _one(evidence, "HospitalCheck")
    if hospital is None:
        if claim is None or len(evidence) != 1:
            return None
        return template(
            "hospital_none_on_claim", claim_id=_need(claim.payload, "claim_id"), label=_label(claim, "claims")
        )
    h, h_label = hospital.payload, _label(hospital, "hospitals", key=hospital.payload.get("hospital_id"))
    values = {k: _need(h, k) for k in ("hospital_name", "hospital_id", "city", "network_status")}
    if claim is not None:
        labels = f"{_label(claim, 'claims')} {h_label}"
        lines = [
            template("hospital_on_claim", claim_id=_need(claim.payload, "claim_id"), labels=labels, **values)
        ]
    else:
        lines = [template("hospital_check", label=h_label, **values)]
    alternatives = h.get("alternatives") or []
    if alternatives:
        rows = [
            f"- {a['hospital_name']} ({a['hospital_id']}) "
            + _label(hospital, "hospitals", key=a["hospital_id"])
            for a in alternatives
            if a.get("hospital_name") and a.get("hospital_id")
        ]
        heading = template("hospital_alternatives", city=values["city"], specialty=_need(h, "specialty"))
        lines.append(heading + "\n" + "\n".join(rows))
    return "\n\n".join(lines)


def _policy_details(evidence: list[Evidence], question: str) -> str | None:
    policy = _one(evidence, "PolicyView")
    if policy is None:
        return None
    p, label = policy.payload, _label(policy, "policies")
    lines = []
    if claim := _one(evidence, "ClaimView"):
        lines.append(
            template(
                "policy_of_claim",
                claim_id=_need(claim.payload, "claim_id"),
                policy_id=_need(p, "policy_id"),
                label=_label(claim, "claims"),
            )
        )
    keys = (
        "policy_id",
        "product_name",
        "policy_type",
        "effective_status",
        "policy_start_date",
        "policy_end_date",
    )
    lines.append(template("policy_details", label=label, **{k: _need(p, k) for k in keys}))
    if p.get("status_conflict") and p.get("policy_status"):
        lines.append(template("policy_status_conflict", policy_status=p["policy_status"], label=label))
    lines.append(
        template(
            "policy_schedule",
            sum_insured=inr(_need(p, "sum_insured")),
            annual_premium=inr(_need(p, "annual_premium")),
            waiting_period_days=_need(p, "waiting_period_days"),
            co_pay_pct=_need(p, "co_pay_pct"),
            deductible=inr(_need(p, "deductible")),
            label=label,
        )
    )
    return "\n\n".join(lines)


_RENDERERS = {
    "claim_status": _claim_status,
    "claim_documents": _claim_documents,
    "hospital_check": _hospital_check,
    "policy_details": _policy_details,
}


# --- helpers ----------------------------------------------------------------------------------------------


def _one(evidence: list[Evidence], kind: str) -> Evidence | None:
    found = [ev for ev in evidence if ev.kind == kind]
    return found[0] if len(found) == 1 else None


def _need(payload: dict[str, Any], key: str) -> Any:
    value = payload.get(key)
    if value is None:
        raise _Missing(key)
    return value


def _label(ev: Evidence, table: str, key: str | None = None) -> str:
    """The evidence's own label for `table` (and `key`); never built here, so V1 always holds."""
    for ref in ev.sources:
        if ref.table == table and (key is None or ref.key == key):
            return ref.label
    raise _Missing(f"{table}:{key}")


def _join(items: list[str]) -> str:
    return ", ".join(str(i) for i in items)
