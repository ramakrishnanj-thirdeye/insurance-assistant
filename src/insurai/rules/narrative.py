"""Deterministic text around the dossier narrative (spec 07 Behaviour 9, spec 06 explain vs assess).

- `question_mode`: "assess" when the question asks for an assessment, else "explain" (no review pause).
- `premise_correction`: a cited correction when the question assumes a status the claim does not have.
- `narrative_input`: the assessment JSON the narrative prompt sees (its only source).
- `narrative_opening`: the templated first line (status, blockers, review need); the model never writes it.
- `complete_narrative`: the completeness guard; the correction and the opening lead, every finding and action
  appears, the reviewer's decision is appended verbatim, repeated paragraphs are removed.
- `render_assessment`: the no-LLM rendering, the final fallback for claim-analysis turns.
"""

import re
from typing import Any, Literal

from insurai.agent.prompts import template
from insurai.formatting import inr
from insurai.rules.engine import dossier_config
from insurai.rules.schemas import ClaimAssessment, ReviewDecision, RuleResult
from insurai.textblocks import append_once, dedupe_paragraphs
from insurai.tools.sources import sql_source

Mode = Literal["assess", "explain"]
CLAUSE_EXCERPT_CHARS = 300
SEVERITY_ORDER = {"blocker": 0, "escalate": 1, "warning": 2, "info": 3}
AMOUNT_FACTS = ("claim_amount", "approved_amount")  # shown to the model in rupees, never as bare numbers


def _phrase(words: str) -> re.Pattern[str]:
    return re.compile(r"\b" + r"\s+".join(re.escape(w) for w in words.split()) + r"\b", re.IGNORECASE)


def _without(text: str, phrases: list[str]) -> str:
    for phrase in sorted(phrases, key=len, reverse=True):
        text = _phrase(phrase).sub(" ", text)
    return text


def question_mode(question: str) -> Mode:
    """Assess only when the question asks for a judgment (analyse, review, decide, approve, ...).

    Status phrases ("under review", "approved") are removed first, so "Why is it under review?" explains."""
    cfg = dossier_config()
    text = _without(_without(question, cfg.premise_ignore), list(cfg.status_words))
    return "assess" if any(_phrase(k).search(text) for k in cfg.assess_keywords) else "explain"


def premise_correction(question: str | None, claim_id: str, claim_status: str | None) -> str | None:
    """ "CLM300210 is Approved, not pending [claims:CLM300210]." when every status word in the question
    contradicts the claim's actual status; None when there is no status word or one of them fits."""
    if not question or not claim_status:
        return None
    cfg = dossier_config()
    text = _without(question, cfg.premise_ignore)
    named: list[str] = []
    for word in sorted(cfg.status_words, key=len, reverse=True):  # "under review" before "review"
        pattern = _phrase(word)
        if pattern.search(text):
            named.append(word)
            text = pattern.sub(" ", text)
    if not named or any(claim_status in cfg.status_words[w] for w in named):
        return None
    label = sql_source("claims", claim_id).label
    return template(
        "premise_correction", claim_id=claim_id, claim_status=claim_status, premise=named[0], label=label
    )


def findings(assessment: ClaimAssessment) -> list[RuleResult]:
    """Fail and review results, blockers first (the order the narrative presents them)."""
    hits = [r for r in assessment.rules if r.status in ("fail", "review")]
    return sorted(hits, key=lambda r: (SEVERITY_ORDER[r.severity], r.status != "fail", r.id))


def counts(assessment: ClaimAssessment) -> dict[str, int]:
    hits = findings(assessment)
    return {
        "findings": len(hits),
        "blockers": sum(r.status == "fail" and r.severity == "blocker" for r in hits),
        "needs_review": sum(r.status == "review" for r in hits),
    }


def citation_of(result: RuleResult, assessment: ClaimAssessment) -> str:
    return result.citation.label if result.citation else sql_source("claims", assessment.claim_id).label


def narrative_input(assessment: ClaimAssessment, correction: str | None = None) -> dict[str, Any]:
    """What the narrative prompt sees: facts that matter, findings with citations, actions, clauses. No counts
    and no review: the opening and the reviewer's line are added verbatim after the model writes."""
    customer = assessment.view == "customer"
    facts = assessment.facts
    keep = (
        "claim_status",
        "claim_date",
        "claim_amount",
        "approved_amount",
        "product_name",
        "diagnosis_or_loss_type",
        "policy_start_date",
        "policy_end_date",
    )
    data: dict[str, Any] = {
        "claim_id": assessment.claim_id,
        "view": assessment.view,
        "claim_citation": sql_source("claims", assessment.claim_id).label,
        "facts": {k: _fact(k, facts.get(k)) for k in keep if k in facts},
        "needs_human_review": assessment.needs_human_review,
        "findings": [
            {
                **({} if customer else {"rule": r.id}),
                "name": r.name,
                "status": r.status,
                "severity": r.severity,
                "message": r.message,
                "citation": citation_of(r, assessment),
            }
            for r in findings(assessment)
        ],
        "untracked_documents": assessment.checklist.untracked,
        "clauses": [
            {"label": c.chunk.citation_label, "text": c.chunk.text[:CLAUSE_EXCERPT_CHARS]}
            for c in assessment.clauses
        ],
    }
    if assessment.next_best_actions:  # left out when empty, so no empty next-steps section is written
        data["next_best_actions"] = assessment.next_best_actions
    if not customer:
        data["consistency_flags"] = [f.name for f in assessment.consistency]
    if correction:
        data["premise_correction"] = correction
    return data


def _fact(key: str, value: Any) -> Any:
    if key in AMOUNT_FACTS and isinstance(value, int | float) and not isinstance(value, bool):
        return inr(value)
    return value


def narrative_opening(assessment: ClaimAssessment) -> str:
    """ "Claim X is <status>; N blockers; needs / doesn't need human review [claims:X]." """
    blockers = counts(assessment)["blockers"]
    return template(
        "narrative_opening",
        claim_id=assessment.claim_id,
        claim_status=assessment.facts.get("claim_status"),
        blockers=template("narrative_blocker_one" if blockers == 1 else "narrative_blockers", n=blockers),
        review=template(
            "narrative_review_needed" if assessment.needs_human_review else "narrative_review_not_needed"
        ),
        label=sql_source("claims", assessment.claim_id).label,
    )


def review_line(review: ReviewDecision) -> str:
    """The reviewer's decision and note, verbatim from the template (never reworded by a model)."""
    return template("review_decision", action=review.action, note=review.note or "(none)")


def _without_status_opener(body: str, claim_id: str) -> str:
    """The model's own status opener ("Claim X is ..." starting a line) removed: the opening states it."""
    opener = re.compile(
        rf"^(\s*)\**claim\s+{re.escape(claim_id)}\**\s+is\b[^.\n]*\.\s*(?:\[[^\]\n]+\]\s*)*", re.IGNORECASE
    )
    return "\n".join(opener.sub(r"\1", line) for line in body.split("\n")).strip()


def _norm(text: str) -> str:
    return " ".join(text.lower().replace("*", "").split()).rstrip(".")


def complete_narrative(text: str, assessment: ClaimAssessment, correction: str | None = None) -> str:
    """The completeness guard: the correction leads, then the templated opening; any finding message or
    action the model left out is appended verbatim with its citation, so every blocker is mentioned whatever
    the model wrote; the reviewer's decision closes it."""
    return complete_narrative_with_additions(text, assessment, correction)[0]


def complete_narrative_with_additions(
    text: str, assessment: ClaimAssessment, correction: str | None = None
) -> tuple[str, list[str]]:
    """`complete_narrative` plus what the guard added: each "Also noted" finding and each "Next steps" action
    (the spec 11 guard_interventions diagnostic); empty when the model's text was complete. The templated
    opening and the reviewer's line are presentation, not interventions."""
    body = text.strip()
    if correction:
        body = body.replace(correction, "").strip()
    body = dedupe_paragraphs(_without_status_opener(body, assessment.claim_id))
    seen = _norm(body)
    missing = [
        f"- {r.message} {citation_of(r, assessment)}"
        for r in findings(assessment)
        if r.message and _norm(r.message) not in seen
    ]
    actions = [a for a in assessment.next_best_actions if _norm(a) not in seen]
    parts = [correction] if correction else []
    parts += [narrative_opening(assessment), body]
    if missing:
        parts.append("Also noted:\n" + "\n".join(missing))
    if actions:
        label = sql_source("claims", assessment.claim_id).label
        parts.append("Next steps:\n" + "\n".join(f"- {a} {label}" for a in actions))
    if assessment.review is not None:
        parts.append(review_line(assessment.review))
    out = ""
    for part in parts:
        out = append_once(out, part)
    return dedupe_paragraphs(out), missing + [f"- {a}" for a in actions]


def render_assessment(assessment: ClaimAssessment, correction: str | None = None) -> str:
    """The assessment as markdown without an LLM: the opening, findings and next steps, each cited, then the
    reviewer's decision (`respond` does not repeat it)."""
    label = sql_source("claims", assessment.claim_id).label
    lines = [correction] if correction else []
    lines.append(narrative_opening(assessment))
    hits = [f"- {r.message} {citation_of(r, assessment)}" for r in findings(assessment) if r.message]
    if hits:
        lines.append("\n".join(hits))
    if assessment.next_best_actions:
        steps = (f"{k}. {a} {label}" for k, a in enumerate(assessment.next_best_actions, start=1))
        lines.append("Next steps:\n" + "\n".join(steps))
    if assessment.review is not None:
        lines.append(review_line(assessment.review))
    return "\n\n".join(lines)
