"""Deterministic intent pruning and promotion (spec 06 routing rules 9 and 10), run by finalize_plan.

Trigger lists come from config/glossary.yaml `routing`: each intent's definition words, the config lists it
names in `from`, and every glossary synonym group sharing a term with them. No LLM, no eval data.
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import yaml

from insurai.agent.resolve import _glossary
from insurai.agent.schemas import Intent
from insurai.retrieval.glossary import load_glossary
from insurai.rules.engine import dossier_config
from insurai.settings import ROOT

REQUIRED_DOCUMENTS_FILE = ROOT / "config" / "required_documents.yaml"


@dataclass(frozen=True)
class RoutingConfig:
    triggers: dict[str, tuple[str, ...]]  # intent type → terms (a trailing * marks a prefix)
    promote: tuple[str, ...]


def _sources(cfg: dict[str, Any]) -> dict[str, list[str]]:
    dossier = dossier_config()
    documents = yaml.safe_load(REQUIRED_DOCUMENTS_FILE.read_text(encoding="utf-8"))["document_types"]
    return {
        "fast_path_status_keywords": list(_glossary()["fast_path"]["status_keywords"]),
        "dossier_status_words": list(dossier.status_words),
        "dossier_assess_keywords": list(dossier.assess_keywords),
        "document_types": list(documents),
        "promote_to_analysis": list(cfg["promote_to_analysis"]),
    }


def _with_synonyms(terms: list[str]) -> list[str]:
    """`terms` plus every glossary synonym group that shares a term with them (case-insensitive)."""
    have = {t.casefold() for t in terms}
    out = list(terms)
    for group in load_glossary().synonyms:
        if have & {g.casefold() for g in group}:
            out += [g for g in group if g.casefold() not in {o.casefold() for o in out}]
    return out


@lru_cache(maxsize=1)
def routing_config() -> RoutingConfig:
    cfg = _glossary()["routing"]
    sources = _sources(cfg)
    triggers: dict[str, tuple[str, ...]] = {}
    for intent, spec in cfg["intent_triggers"].items():
        terms = list(spec.get("words", []))
        for name in spec.get("from", []):
            terms += [t for t in sources[name] if t not in terms]
        triggers[intent] = tuple(_with_synonyms(terms))
    return RoutingConfig(triggers=triggers, promote=tuple(cfg["promote_to_analysis"]))


@lru_cache(maxsize=512)
def _pattern(term: str) -> re.Pattern[str]:
    if term.endswith("*"):
        return re.compile(rf"(?<!\w){re.escape(term[:-1])}", re.IGNORECASE)
    words = r"\s+".join(re.escape(w) for w in term.split())
    return re.compile(rf"(?<!\w){words}s?(?!\w)", re.IGNORECASE)


def mentions(message: str, terms: tuple[str, ...]) -> bool:
    return any(_pattern(t).search(message) for t in terms)


def promote(intents: list[Intent], message: str) -> tuple[list[Intent], list[bool]]:
    """Rule 10: claim_status intents become claim_analysis when the message asks for a summary or a why.
    Returns the intents and, per position, whether it was promoted (promoted intents run in explain mode)."""
    if not mentions(message, routing_config().promote):
        return intents, [False] * len(intents)
    flags = [i.type == "claim_status" for i in intents]
    out = [
        i.model_copy(update={"type": "claim_analysis"}) if f else i
        for i, f in zip(intents, flags, strict=True)
    ]
    return out, flags


def prune(intents: list[Intent], message: str) -> list[int]:
    """Rule 9: positions of the intents to keep, dropping those whose trigger words are absent from the
    message. A single intent is never pruned, and a plan whose every intent would be pruned is kept."""
    every = list(range(len(intents)))
    if len(intents) < 2:
        return every
    triggers = routing_config().triggers
    kept = [k for k, i in enumerate(intents) if i.type not in triggers or mentions(message, triggers[i.type])]
    return kept or every


def dedupe(intents: list[Intent]) -> list[Intent]:
    """A claim_status intent on a claim that also has a claim_analysis intent: the dossier covers it.
    Run after finalize_plan fills claim IDs; an intent without one is kept."""
    analysed = {i.entities.claim_id for i in intents if i.type == "claim_analysis" and i.entities.claim_id}
    return [i for i in intents if not (i.type == "claim_status" and i.entities.claim_id in analysed)]
