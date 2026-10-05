"""Deterministic output checks V1–V4 (spec 08 Output checks). V5–V7 arrive in M7.

V1 citation validity · V2 citation presence · V3 number provenance · V4 no guarantee.
"""

import json
import re
from datetime import date
from functools import lru_cache
from typing import Any

from insurai.agent.schemas import AnswerDraft, Evidence
from insurai.guardrails.schemas import CheckOutcome, VerificationReport
from insurai.tools.messages import guardrails
from insurai.tools.schemas import Persona
from insurai.tools.sources import label_regexes

NO_RESULT_KINDS = frozenset({"not_found", "access_denied", "unavailable"})

# Order matters: dates and IDs first so their digits are not read again as bare numbers.
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_ID = re.compile(r"\b(?:CLM|POL|CUST|HOSP)\d+\b")
_NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
_LIST_MARKER = re.compile(r"^\s*\d+[.)]\s+", re.MULTILINE)


def number_tokens(text: str) -> set[str]:
    """Normalised numeric tokens: ISO dates, IDs, and numbers with ₹, commas and suffixes stripped.

    Indian and western grouping both normalise (5,00,000 and 500,000 → 500000); 24-month → 24; 12.50 → 12.5.
    """
    tokens: set[str] = set()
    for rx in (_DATE, _ID):
        tokens.update(rx.findall(text))
        text = rx.sub(" ", text)
    for raw in _NUMBER.findall(text):
        if norm := _norm_number(raw):
            tokens.add(norm)
    return tokens


def _norm_number(raw: str) -> str | None:
    digits = raw.replace(",", "").rstrip(".")
    try:
        value = float(digits)
    except ValueError:
        return None
    return str(int(value)) if value == int(value) else repr(value)


def evidence_tokens(evidence: list[Evidence]) -> set[str]:
    """Every number in evidence payloads, summaries and labels, plus list lengths (counts are evidence)."""
    tokens: set[str] = set()
    for ev in evidence:
        tokens |= number_tokens(json.dumps(ev.payload, default=str, ensure_ascii=False))
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


def rewrite_guarantees(text: str) -> str:
    """Replace every sentence that makes a guarantee with the mandated wording (once)."""
    mandated = guardrails()["no_guarantee"]["mandated_wording"]
    out: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if guarantee_hits(sentence):
            if mandated not in out:
                out.append(mandated)
        else:
            out.append(sentence)
    return " ".join(out)


def verify(
    draft: AnswerDraft, evidence: list[Evidence], persona: Persona, question: str, as_of: date | None = None
) -> VerificationReport:
    answer = draft.answer_markdown
    allowed_labels = {ref.label for ev in evidence for ref in ev.sources}
    used = labels_in(answer)
    invalid = [label for label in dict.fromkeys(used + draft.citations) if label not in allowed_labels]

    has_results = any(ev.kind not in NO_RESULT_KINDS for ev in evidence)
    v2_ok = not has_results or bool(used)

    allowed_numbers = evidence_tokens(evidence) | number_tokens(question)
    if as_of is not None:
        allowed_numbers.add(as_of.isoformat())
    answer_numbers = number_tokens(_LIST_MARKER.sub("", strip_labels(answer)))
    orphans = sorted(answer_numbers - allowed_numbers)

    hits = guarantee_hits(answer)
    checks = [
        CheckOutcome(check="V1", passed=not invalid, detail=", ".join(invalid)),
        CheckOutcome(check="V2", passed=v2_ok, detail="" if v2_ok else "factual answer without citations"),
        CheckOutcome(check="V3", passed=not orphans, detail=", ".join(orphans)),
        CheckOutcome(check="V4", passed=not hits, detail=", ".join(hits)),
    ]
    feedback = []
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
    return VerificationReport(
        passed=all(c.passed for c in checks),
        checks=checks,
        orphan_numbers=orphans,
        invalid_citations=invalid,
        feedback=" ".join(feedback),
    )
