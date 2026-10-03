"""Guardrails config read by the tool layer: refusal texts and citation formats (config/guardrails.yaml)."""

from functools import lru_cache
from typing import Any

import yaml

from insurai.settings import ROOT

GUARDRAILS_FILE = ROOT / "config" / "guardrails.yaml"


@lru_cache(maxsize=1)
def guardrails() -> dict[str, Any]:
    return yaml.safe_load(GUARDRAILS_FILE.read_text(encoding="utf-8"))


def refusal(code: str) -> str:
    return str(guardrails()["refusals"][code])
