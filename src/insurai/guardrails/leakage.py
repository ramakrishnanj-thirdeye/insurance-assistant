"""V5 PII leakage (spec 08 Output layer).

Fails when the answer carries a PII pattern match (Aadhaar, PAN, phone, email, card, IFSC) that is not in
the evidence, or a customer name shown to a persona whose hidden columns include customer_name. Details
name the pattern or say "customer name", never the value, so the trace does not repeat the leak.
"""

import json
import re
from functools import lru_cache
from typing import Any

from insurai.agent.schemas import Evidence
from insurai.guardrails.pii import patterns
from insurai.observability import get_logger
from insurai.tools.access import load_personas
from insurai.tools.base import fetch_all
from insurai.tools.schemas import Persona

log = get_logger(__name__)

_SEPARATORS = re.compile(r"[\s-]")


def pii_leaks(answer: str, evidence: list[Evidence]) -> list[str]:
    """Pattern names of PII matches in `answer` whose value is absent from every evidence payload."""
    haystack = _SEPARATORS.sub("", _evidence_text(evidence))
    leaks: list[str] = []
    for name, pattern in patterns():
        for match in pattern.finditer(answer):
            if _SEPARATORS.sub("", match.group(0)) not in haystack and name not in leaks:
                leaks.append(name)
    return leaks


def name_leaks(answer: str, evidence: list[Evidence], persona: Persona) -> int:
    """How many distinct customer names appear in `answer` when `persona` may not see customer names."""
    if "customer_name" not in load_personas()[persona].hidden_columns:
        return 0
    names = known_names() | evidence_names(evidence)
    if not names:
        return 0
    rx = re.compile(r"\b(?:" + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)) + r")\b")
    return len(set(rx.findall(answer)))


@lru_cache(maxsize=1)
def known_names() -> frozenset[str]:
    """Every distinct customer name in the warehouse (300 names); empty when the warehouse is unavailable."""
    try:
        rows = fetch_all(
            "SELECT DISTINCT customer_name FROM silver.customers WHERE customer_name IS NOT NULL", []
        )
    except Exception:  # no warehouse (fresh clone, unit tests): evidence names still apply
        log.warning("V5: customer names unavailable from the warehouse; using evidence names only")
        return frozenset()
    return frozenset(str(r["customer_name"]) for r in rows)


def evidence_names(evidence: list[Evidence]) -> set[str]:
    names: set[str] = set()
    for ev in evidence:
        _collect_names(ev.payload, names)
    return names


def _collect_names(value: Any, out: set[str]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            if k == "customer_name" and isinstance(v, str) and v.strip():
                out.add(v.strip())
            else:
                _collect_names(v, out)
    elif isinstance(value, list):
        for v in value:
            _collect_names(v, out)


def _evidence_text(evidence: list[Evidence]) -> str:
    return " ".join(
        json.dumps(ev.payload, default=str, ensure_ascii=False) + " " + ev.summary for ev in evidence
    )
