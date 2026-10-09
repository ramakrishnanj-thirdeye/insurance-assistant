"""Deterministic input checks (spec 08 input layer): PII masking, injection markers, scope keywords, and the
guarantee-request flag (answered from the wording, never refused).

The small-LLM confirmation of injection hits is deferred (3-day scope); a marker hit blocks.
"""

import re
from functools import lru_cache

from insurai.guardrails.pii import mask
from insurai.guardrails.schemas import GuardResult
from insurai.tools.messages import guardrails
from insurai.tools.schemas import Persona


@lru_cache(maxsize=1)
def _guarantee_patterns() -> list[re.Pattern[str]]:
    return [re.compile(p, re.IGNORECASE) for p in guardrails()["guarantee_request"]["patterns"]]


def is_guarantee_request(text: str) -> bool:
    return any(p.search(text) for p in _guarantee_patterns())


def check_input(text: str, persona: Persona) -> GuardResult:
    masked, pii = mask(text)
    g = guardrails()
    lowered = masked.casefold()
    if hits := [m for m in g["injection_markers"] if m.casefold() in lowered]:
        return GuardResult(
            allowed=False, code="INJECTION", masked_text=masked, pii_found=pii, reasons=[f"marker: {hits[0]}"]
        )
    keywords = g["scope"].get("out_of_scope_keywords", [])
    if hits := [k for k in keywords if k.casefold() in lowered]:
        return GuardResult(
            allowed=False,
            code="OUT_OF_SCOPE",
            masked_text=masked,
            pii_found=pii,
            reasons=[f"scope: {hits[0]}"],
        )
    return GuardResult(
        allowed=True, masked_text=masked, pii_found=pii, guarantee_request=is_guarantee_request(masked)
    )
