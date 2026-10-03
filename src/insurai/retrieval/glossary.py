"""Deterministic query expansion from config/glossary.yaml (spec 04 stage 1)."""

import re
from functools import lru_cache

import yaml
from pydantic import BaseModel, ConfigDict

from insurai.settings import ROOT

GLOSSARY_FILE = ROOT / "config" / "glossary.yaml"


class Glossary(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    products: dict[str, list[str]]
    synonyms: list[list[str]]
    section_hints: dict[str, list[int]]


@lru_cache(maxsize=1)
def load_glossary() -> Glossary:
    return Glossary.model_validate(yaml.safe_load(GLOSSARY_FILE.read_text(encoding="utf-8")))


def expand(query: str) -> tuple[str, list[int]]:
    """Append synonyms of every glossary phrase found in `query`; collect section hints in glossary order.

    Phrases match case-insensitively on word boundaries. Terms already in the query are not repeated.
    Hints are read from the expanded query, so a synonym can contribute its topic's sections.
    """
    glossary = load_glossary()
    added: list[str] = []
    for group in glossary.synonyms:
        if any(_occurs(term, query) for term in group):
            for term in group:
                if not _occurs(term, query) and term.lower() not in (a.lower() for a in added):
                    added.append(term)
    expanded = f"{query} {' '.join(added)}" if added else query

    hints: list[int] = []
    for keyword, sections in glossary.section_hints.items():
        if _occurs(keyword, expanded, plural=True):
            hints.extend(s for s in sections if s not in hints)
    return expanded, hints


def _occurs(term: str, text: str, plural: bool = False) -> bool:
    suffix = r"(?:s|es)?" if plural else ""
    return re.search(rf"(?<!\w){re.escape(term)}{suffix}(?!\w)", text, re.IGNORECASE) is not None
