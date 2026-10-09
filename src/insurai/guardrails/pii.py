"""PII masking with the patterns in config/guardrails.yaml (spec 08 input layer step 1, and Logging)."""

import re
from functools import lru_cache
from typing import Any

from insurai.tools.messages import guardrails


@lru_cache(maxsize=1)
def patterns() -> list[tuple[str, re.Pattern[str]]]:
    return [(name, re.compile(rx)) for name, rx in guardrails()["pii_patterns"].items()]


def mask(text: str) -> tuple[str, list[str]]:
    """Replace every PII match with `[NAME]`; return the masked text and the pattern names found.

    Patterns apply in config order, so a 12-digit Aadhaar is masked before the card pattern sees it.
    """
    found: list[str] = []
    for name, pattern in patterns():
        text, n = pattern.subn(f"[{name}]", text)
        if n and name not in found:
            found.append(name)
    return text, found


def redact_for_logs(obj: Any, persona: str | None = None) -> Any:
    """`obj` with PII masked in every string (dicts, lists and tuples walked); for a customer-persona
    session, `customer_name` keys are dropped too (spec 08 Logging)."""
    if isinstance(obj, str):
        return mask(obj)[0]
    if isinstance(obj, dict):
        return {
            k: redact_for_logs(v, persona)
            for k, v in obj.items()
            if not (persona == "customer" and k == "customer_name")
        }
    if isinstance(obj, list | tuple):
        return type(obj)(redact_for_logs(v, persona) for v in obj)
    return obj
