"""Guarantee requests (spec 08 input rule 4): answered from the policy wording, never refused.

`augment` runs inside finalize_plan (with pruning and promotion, so the routing eval scores the plan that
runs). It makes sure a policy_question carries the pinned sections (§14, §15, fetched by chunk id, not
ranked), adds a claim_analysis when a claim is in context and nothing on the turn says what that claim still
needs, and forces explain mode ("approved" in a guarantee question is not a request for a judgment).

`ensure_guarantee_answer` is the deterministic completion before verify: it leads with the mandated wording
cited to the §15 chunk that carries it, and appends what the claim still needs when the answer left it out.

`guarantee_draft` answers a guarantee-only turn (`sole_claim`) with no generator call and no narrative
(AC-08-24): the turn's only concern is the claim, and every sentence of the answer is a template or a fact.
"""

from typing import Any

from insurai.agent.answers import claim_status_text
from insurai.agent.prompts import template
from insurai.agent.schemas import AnswerDraft, Entities, Evidence, Intent
from insurai.guardrails.verify import labels_in, mandated_span
from insurai.tools.messages import guardrails

NEEDS_INTENTS = frozenset({"claim_analysis", "claim_documents"})


def config() -> dict[str, Any]:
    return dict(guardrails()["guarantee_request"])


def mandated_wording() -> str:
    return str(guardrails()["no_guarantee"]["mandated_wording"])


def augment(intents: list[Intent], message: str, claim_id: str | None, product: str | None) -> list[Intent]:
    pinned = list(config()["pinned_sections"])
    out = [i.model_copy(update={"mode": "explain"}) if i.type == "claim_analysis" else i for i in intents]
    if claim_id and not any(i.type in NEEDS_INTENTS and i.entities.claim_id == claim_id for i in out):
        out.append(
            Intent(
                id="g1",
                type="claim_analysis",
                entities=Entities(claim_id=claim_id),
                sub_question=message,
                mode="explain",
                question=message,
                added_by="guarantee",
            )
        )
    questions = [k for k, i in enumerate(out) if i.type == "policy_question"]
    if questions:
        k = questions[0]
        out[k] = out[k].model_copy(update={"pinned_sections": pinned})
    else:
        out.append(
            Intent(
                id="g2",
                type="policy_question",
                entities=Entities(product=product),
                sub_question=message,
                pinned_sections=pinned,
                added_by="guarantee",
            )
        )
    if sole_claim(out):  # the answer is built from the assessment: no narrative to write (AC-08-24)
        out = [i.model_copy(update={"narrate": False}) if i.type == "claim_analysis" else i for i in out]
    return out


def sole_claim(intents: list[Intent]) -> str | None:
    """The claim of a guarantee-only turn: one explain-mode claim_analysis on a claim, and nothing else but
    the policy_question the augmentation added. A turn with any other concern is synthesized."""
    analyses = [i for i in intents if i.type == "claim_analysis"]
    if len(analyses) != 1 or analyses[0].mode != "explain" or not analyses[0].entities.claim_id:
        return None
    others = [i for i in intents if i.type != "claim_analysis"]
    if not all(i.type == "policy_question" and i.added_by == "guarantee" for i in others):
        return None
    return analyses[0].entities.claim_id


def guarantee_draft(evidence: list[Evidence], claim_id: str, question: str) -> AnswerDraft | None:
    """A guarantee-only answer without a generator call (AC-08-24): the mandated wording cited to §15, the
    claim's status, and what it still needs (the assessment's next steps and the document checklist), each
    cited. None when the claim's facts or assessment are missing (not found, denied): the usual path
    answers."""
    claim = next(
        (e for e in evidence if e.kind == "ClaimView" and e.payload.get("claim_id") == claim_id), None
    )
    assessment = next(
        (e for e in evidence if e.kind == "ClaimAssessment" and e.payload.get("claim_id") == claim_id), None
    )
    if claim is None or assessment is None:
        return None
    parts = [template("guarantee_lead", label=s15_label(evidence) or "").rstrip()]
    parts.append(claim_status_text(claim, question))
    needs = _needs_lines(evidence, claim_id, "") or [template("guarantee_needs_heading", claim_id=claim_id)]
    label = str(assessment.payload.get("claim_citation") or "")
    needs[1:1] = [f"- {step} {label}".rstrip() for step in assessment.payload.get("next_best_actions", [])]
    if len(needs) > 1:
        parts.append("\n".join(needs))
    text = "\n\n".join(parts)
    return AnswerDraft(answer_markdown=text, citations=labels_in(text))


def s15_label(evidence: list[Evidence]) -> str | None:
    """The label of the cited section's chunk that carries the mandated wording, else its first chunk."""
    section = int(config()["cite_section"])
    wording = mandated_wording().casefold().rstrip(".")
    first: str | None = None
    for ev in evidence:
        if ev.kind != "RetrievalResult":
            continue
        for clause, ref in zip(ev.payload.get("clauses", []), ev.sources, strict=False):
            if ref.section_no != section:
                continue
            if wording in str(clause.get("text", "")).casefold():
                return ref.label
            first = first or ref.label
    return first


def ensure_guarantee_answer(
    draft: AnswerDraft, evidence: list[Evidence], claim_id: str | None
) -> AnswerDraft:
    text = draft.answer_markdown
    label = s15_label(evidence)
    span = mandated_span(text)
    if span is None:
        text = template("guarantee_lead", label=label or "").rstrip() + "\n\n" + text
    elif label and label not in text:
        text = f"{text[: span.end()]} {label}{text[span.end() :]}"
    if claim_id and (needs := _needs_lines(evidence, claim_id, text)):
        text = text.rstrip() + "\n\n" + "\n".join(needs)
    if text == draft.answer_markdown:
        return draft
    return draft.model_copy(update={"answer_markdown": text, "citations": labels_in(text)})


def _needs_lines(evidence: list[Evidence], claim_id: str, text: str) -> list[str]:
    """What the claim still needs (document checklist), unless the answer already names every document."""
    for ev in evidence:
        checklist = _checklist(ev, claim_id)
        if checklist is None:
            continue
        names = [*checklist.get("missing", []), *checklist.get("pending", []), *checklist.get("rejected", [])]
        if names and all(n in text for n in names):
            return []
        label = next((r.label for r in ev.sources if "claim_documents" in r.label), None)
        label = label or (ev.sources[0].label if ev.sources else "")
        lines = [template("guarantee_needs_heading", claim_id=claim_id)]
        for key, name in (
            ("missing", "claim_documents_missing"),
            ("pending", "claim_documents_pending"),
            ("rejected", "claim_documents_rejected"),
        ):
            if checklist.get(key):
                lines.append(
                    "- " + template(name, claim_id=claim_id, documents=", ".join(checklist[key]), label=label)
                )
        if len(lines) == 1:
            if f"{claim_id}" in text and "no documents are missing" in text.casefold():
                return []
            lines.append("- " + template("claim_documents_none_missing", claim_id=claim_id, label=label))
        return lines
    return []


def _checklist(ev: Evidence, claim_id: str) -> dict[str, Any] | None:
    if ev.kind == "ClaimAssessment" and ev.payload.get("claim_id") == claim_id:
        return dict(ev.payload.get("checklist") or {})
    if ev.kind == "DocumentChecklist" and ev.payload.get("claim_id") == claim_id:
        return dict(ev.payload)
    return None
