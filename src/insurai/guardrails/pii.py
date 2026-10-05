"""PII masking with the patterns in config/guardrails.yaml (spec 08 input layer, step 1)."""

import re
from functools import lru_cache

from insurai.tools.messages import guardrails


@lru_cache(maxsize=1)
def _patterns() -> list[tuple[str, re.Pattern[str]]]:
    return [(name, re.compile(rx)) for name, rx in guardrails()["pii_patterns"].items()]


def mask(text: str) -> tuple[str, list[str]]:
    """Replace every PII match with `[NAME]`; return the masked text and the pattern names found.

    Patterns apply in config order, so a 12-digit Aadhaar is masked before the card pattern sees it.
    """
    found: list[str] = []
    for name, pattern in _patterns():
        text, n = pattern.subn(f"[{name}]", text)
        if n and name not in found:
            found.append(name)
    return text, found
