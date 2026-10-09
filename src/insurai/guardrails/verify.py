"""Output checks (spec 08 Output layer): deterministic V1–V6 first, then the V7 judge.

V1 citation validity · V2 citation presence · V3 number provenance · V4 no guarantee · V5 PII leakage ·
V6 hidden fields (customer persona) · V7 groundedness (LLM judge, injected as `judge` so this module stays
pure; it runs only when V1–V6 pass, so a draft that will be retried anyway costs no judge call).
"""

import json
import re
from collections.abc import Callable
from datetime import date
from functools import lru_cache
from typing import Any

from insurai.agent.schemas import AnswerDraft, Evidence
from insurai.guardrails.hidden import hidden_hits
from insurai.guardrails.leakage import name_leaks, pii_leaks
from insurai.guardrails.numbers import number_tokens
from insurai.guardrails.pii import mask
from insurai.guardrails.schemas import CheckOutcome, GroundednessVerdict, HiddenValues, VerificationReport
from insurai.tools.messages import guardrails
from insurai.tools.schemas import Persona
from insurai.tools.sources import label_regexes

NO_RESULT_KINDS = frozenset({"not_found", "access_denied", "unavailable"})
# Payload keys with LLM-written text (the dossier narrative): shown to the synthesizer, never a number source.
MODEL_WRITTEN_KEYS = frozenset({"narrative"})

# V7: the judge on a model-written answer; None means the judge failed (V7 is then skipped, never passed).
Judge = Callable[[str, list[Evidence]], GroundednessVerdict | None]

_LIST_MARKER = re.compile(r"^\s*\d+[.)]\s+", re.MULTILINE)
_PSEUDO_LABEL = re.compile(r"\[e\d+\]")  # an evidence-block number copied as a citation (M4 root cause)


def evidence_tokens(evidence: list[Evidence]) -> set[str]:
    """Every number in evidence payloads, summaries and labels, plus list lengths (counts are evidence)."""
    tokens: set[str] = set()
    for ev in evidence:
        payload = {k: v for k, v in ev.payload.items() if k not in MODEL_WRITTEN_KEYS}
        tokens |= number_tokens(json.dumps(payload, default=str, ensure_ascii=False))
        tokens |= number_tokens(ev.summary)
        tokens |= {str(n) for n in _list_lengths(ev.payload)}
        for ref in ev.sources:
            tokens |= number_tokens(ref.label)
    return tokens


def _list_lengths(value: Any) -> set[int]:
    if isinstance(value, dict):
        return set().union(*(_list_lengths(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return {len(value)}.union(*(_list_lengths(v) for v in value))
    return set()


def labels_in(text: str) -> list[str]:
    sql_re, policy_re = label_regexes()
    found = sql_re.findall(text) + policy_re.findall(text)
    return list(dict.fromkeys(found))


def strip_labels(text: str) -> str:
    sql_re, policy_re = label_regexes()
    return policy_re.sub(" ", sql_re.sub(" ", text))


@lru_cache(maxsize=1)
def _guarantee_patterns() -> list[re.Pattern[str]]:
    return [re.compile(p, re.IGNORECASE) for p in guardrails()["no_guarantee"]["patterns"]]


def guarantee_hits(text: str) -> list[str]:
    return [m.group(0) for p in _guarantee_patterns() if (m := p.search(text))]


def mandated_span(text: str) -> re.Match[str] | None:
    """Where the mandated wording appears, case-insensitive and with or without its final period (models write
    "… claim assessment [label]." as often as "… claim assessment.")."""
    stem = guardrails()["no_guarantee"]["mandated_wording"].rstrip(".")
    return re.search(re.escape(stem) + r"\.?", text, re.IGNORECASE)


def rewrite_guarantees(text: str) -> str:
    """Replace every sentence that makes a guarantee with the mandated wording (once per answer). Lines are
    kept, so markdown lists and paragraphs keep their shape."""
    mandated = guardrails()["no_guarantee"]["mandated_wording"]
    used = mandated_span(text) is not None  # already stated (e.g. the guarantee lead): drop promises only
    lines: list[str] = []
    for line in text.split("\n"):
        if not guarantee_hits(line):
            lines.append(line)
            continue
        out: list[str] = []
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            if not guarantee_hits(sentence):
                out.append(sentence)
            elif not used:
                out.append(mandated)
                used = True
        lines.append(" ".join(out))
    return "\n".join(lines)


def verify(
    draft: AnswerDraft,
    evidence: list[Evidence],
    persona: Persona,
    question: str,
    as_of: date | None = None,
    *,
    hidden: HiddenValues | None = None,
    judge: Judge | None = None,
) -> VerificationReport:
    answer = draft.answer_markdown
    allowed_labels = {ref.label for ev in evidence for ref in ev.sources}
    used = labels_in(answer)
    pseudo = list(dict.fromkeys(_PSEUDO_LABEL.findall(answer)))
    invalid = [label for label in dict.fromkeys(used + draft.citations) if label not in allowed_labels]
    invalid += pseudo

    has_results = any(ev.kind not in NO_RESULT_KINDS for ev in evidence)
    v2_ok = not has_results or bool(used)

    allowed_numbers = evidence_tokens(evidence) | number_tokens(question)
    if as_of is not None:
        allowed_numbers.add(as_of.isoformat())
    answer_numbers = number_tokens(_LIST_MARKER.sub("", strip_labels(answer)))
    # Masked: an orphan may be a phone or Aadhaar number (V5), never repeated in the trace or the feedback.
    orphans = sorted(dict.fromkeys(mask(n)[0] for n in answer_numbers - allowed_numbers))

    hits = guarantee_hits(answer)
    pii = pii_leaks(answer, evidence)
    names = name_leaks(answer, evidence, persona)
    v5_detail = ", ".join([*pii, *([f"{names} customer name(s)"] if names else [])])
    revealed = hidden_hits(answer, hidden) if persona == "customer" else []
    checks = [
        CheckOutcome(check="V1", passed=not invalid, detail=", ".join(invalid)),
        CheckOutcome(check="V2", passed=v2_ok, detail="" if v2_ok else "factual answer without citations"),
        CheckOutcome(check="V3", passed=not orphans, detail=", ".join(orphans)),
        CheckOutcome(check="V4", passed=not hits, detail=", ".join(hits)),
        CheckOutcome(check="V5", passed=not v5_detail, detail=v5_detail),
        CheckOutcome(check="V6", passed=not revealed, detail=", ".join(revealed)),
    ]
    feedback = []
    if pseudo:
        feedback.append(
            f"{', '.join(pseudo)} are not citations. Cite with the labels in each evidence block's source "
            "attribute, copied exactly."
        )
    if invalid:
        feedback.append(f"Remove or replace citation labels not in the evidence: {', '.join(invalid)}.")
    if not v2_ok:
        feedback.append("End every factual sentence with a citation label copied from the evidence sources.")
    if orphans:
        feedback.append(
            f"These numbers are not in the evidence; remove them or copy exact values: {orphans}."
        )
    if hits:
        feedback.append("Do not promise outcomes; use: " + guardrails()["no_guarantee"]["mandated_wording"])
    if v5_detail:
        feedback.append(
            "Remove personal data that is not in the evidence (IDs, phone numbers, emails, card or bank "
            "numbers) and any customer name."
        )
    if revealed:
        feedback.append(
            "This is a customer: never mention fraud scores, manual review flags or risk segments, "
            "or their values."
        )

    unsupported: list[str] = []
    if judge is not None and all(c.passed for c in checks):
        v7, unsupported = v7_outcome(judge(answer, evidence))
        checks.append(v7)
        if not v7.passed:
            feedback.append(_v7_feedback(unsupported, v7.detail))
    return VerificationReport(
        passed=all(c.passed for c in checks),
        checks=checks,
        orphan_numbers=orphans,
        invalid_citations=invalid,
        unsupported_claims=unsupported,
        feedback=" ".join(feedback),
    )


CONFLICT_NOT_RENDERED = "conflict shown without both values and the precedence sentence"


def v7_outcome(verdict: GroundednessVerdict | None) -> tuple[CheckOutcome, list[str]]:
    """V7 from the judge's verdict: fails on any unsupported claim or an unrendered conflict."""
    if verdict is None:
        return CheckOutcome(check="V7", passed=True, skipped=True, detail="judge error"), []
    unsupported = [c.text for c in verdict.claims if not c.supported]
    problems = [f"{len(unsupported)} unsupported claim(s)"] if unsupported else []
    if verdict.conflict_rule_followed is False:
        problems.append(CONFLICT_NOT_RENDERED)
    return CheckOutcome(check="V7", passed=not problems, detail="; ".join(problems)), unsupported


def v7_skipped(detail: str) -> CheckOutcome:
    return CheckOutcome(check="V7", passed=True, skipped=True, detail=detail)


def _v7_feedback(unsupported: list[str], detail: str) -> str:
    parts = []
    if unsupported:
        parts.append(f"Remove or fix statements the evidence does not support: {unsupported}.")
    if CONFLICT_NOT_RENDERED in detail:
        parts.append(
            "Show both the policy schedule value and the product wording value, then: "
            + guardrails()["conflict_rendering"]["precedence_sentence"]
        )
    return " ".join(parts)
