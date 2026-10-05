"""Message and action rendering (spec 07 Behaviour 3): rupees with Indian grouping, ISO dates, lists joined
with commas, raw codes shown in words (config/rules.yaml `formats`). A rendered text never keeps a `{`.
"""

import re
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from insurai.formatting import inr

PLACEHOLDER = re.compile(r"\{(\w+)\}")


class Formats(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    inr: frozenset[str] = frozenset()
    none: str = "none"
    labels: dict[str, dict[str, str]] = Field(default_factory=dict)


class RenderError(ValueError):
    """A template kept an unresolved placeholder or brace."""


def placeholders(template: str) -> list[str]:
    return PLACEHOLDER.findall(template)


def format_value(name: str, value: Any, fmt: Formats) -> str:
    if value is None:
        return fmt.none
    if isinstance(value, list | tuple):
        return ", ".join(str(v) for v in value) if value else fmt.none
    if name in fmt.inr and isinstance(value, int | float | Decimal) and not isinstance(value, bool):
        return inr(value)
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float | Decimal):
        return format(float(value), "g")
    text = str(value)
    return fmt.labels.get(name, {}).get(text, text)


def render(template: str, values: Mapping[str, Any], fmt: Formats) -> str:
    """`template` with every {name} replaced by its formatted value; raises RenderError if one is unknown."""

    def sub(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            raise RenderError(f"unknown placeholder {{{name}}} in {template!r}")
        return format_value(name, values[name], fmt)

    text = PLACEHOLDER.sub(sub, template)
    if "{" in text or "}" in text:
        raise RenderError(f"unresolved brace in {text!r}")
    return text


def jsonable(value: Any) -> Any:
    """A warehouse value as JSON: dates as ISO strings, decimals as floats, lists element-wise."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    return value
