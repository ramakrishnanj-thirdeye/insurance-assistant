"""Deterministic input checks (spec 08 input layer): PII masking, injection markers, scope keywords.

The small-LLM confirmation of injection hits arrives with spec 08 in M7; until then a marker hit blocks.
"""

from insurai.guardrails.pii import mask
from insurai.guardrails.schemas import GuardResult
from insurai.tools.messages import guardrails
from insurai.tools.schemas import Persona


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
    return GuardResult(allowed=True, masked_text=masked, pii_found=pii)
