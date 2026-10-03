"""ID formats (spec 05 behaviour 1): validated before any query; a bad format is NotFound with a hint."""

import re
from typing import Literal

from insurai.tools.messages import refusal
from insurai.tools.schemas import NotFound

IdKind = Literal["claim", "policy", "customer", "hospital"]

PATTERNS: dict[IdKind, re.Pattern[str]] = {
    "claim": re.compile(r"CLM\d{6}"),
    "policy": re.compile(r"POL\d{6}"),
    "customer": re.compile(r"CUST\d{6}"),
    "hospital": re.compile(r"HOSP\d{4}"),
}
EXAMPLES: dict[IdKind, str] = {
    "claim": "CLM300210",
    "policy": "POL218917",
    "customer": "CUST139920",
    "hospital": "HOSP1257",
}


def validate_id(kind: IdKind, value: str) -> NotFound | None:
    """None when `value` has the right shape, otherwise NotFound naming the expected format."""
    if PATTERNS[kind].fullmatch(value or ""):
        return None
    return NotFound(
        entity=kind, message=f"{value!r} is not a valid {kind} ID; {kind} IDs look like {EXAMPLES[kind]}."
    )


def not_found(kind: str, value: str) -> NotFound:
    return NotFound(entity=kind, message=refusal("NOT_FOUND").format(entity=f"{kind} {value}"))
