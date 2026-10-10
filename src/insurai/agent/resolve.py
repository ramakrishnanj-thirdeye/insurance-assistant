"""Deterministic entity resolution (spec 06 resolve_context): regex IDs, product gazetteer, follow-ups,
and the fast-path test. No LLM.
"""

import re
from functools import lru_cache
from typing import Any

import yaml
from rapidfuzz import fuzz

from insurai.agent.schemas import Entities, Intent, Plan
from insurai.retrieval.glossary import GLOSSARY_FILE
from insurai.tools.ids import PATTERNS

FUZZY_MIN = 90  # config/glossary.yaml: aliases match case-insensitively, then rapidfuzz >= 90
_ID_FIELDS = {
    "claim": "claim_id",
    "policy": "policy_id",
    "customer": "customer_id",
    "hospital": "hospital_id",
}


@lru_cache(maxsize=1)
def _glossary() -> dict[str, Any]:
    return yaml.safe_load(GLOSSARY_FILE.read_text(encoding="utf-8"))


def product_names() -> list[str]:
    return list(_glossary()["products"])


def _word_re(phrase: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(phrase)}(?!\w)", re.IGNORECASE)


def find_ids(text: str) -> dict[str, list[str]]:
    """Every well-formed ID in the text, by entity field, in order of appearance (deduplicated)."""
    found: dict[str, list[str]] = {}
    for kind, pattern in PATTERNS.items():
        ids = re.findall(rf"\b{pattern.pattern}\b", text)
        if ids:
            found[_ID_FIELDS[kind]] = list(dict.fromkeys(ids))
    return found


def match_product(text: str) -> str | None:
    """Canonical product named in the text: exact name or alias first, then fuzzy name match ≥ 90."""
    products: dict[str, list[str]] = _glossary()["products"]
    for canonical, aliases in products.items():
        if any(_word_re(term).search(text) for term in (canonical, *aliases)):
            return canonical
    lowered = text.lower()
    best, score = None, 0.0
    for canonical in products:
        s = fuzz.partial_ratio(canonical.lower(), lowered)
        if s > score:
            best, score = canonical, s
    return best if score >= FUZZY_MIN else None


def canonical_product(name: str | None) -> str | None:
    """Map a planner-supplied product name to its canonical form; None when it is not a known product."""
    if not name:
        return None
    for canonical in product_names():
        if canonical.lower() == name.strip().lower():
            return canonical
    return match_product(name)


def resolve_entities(text: str) -> Entities:
    """Entities stated in this message: the first ID of each kind and a product."""
    ids = find_ids(text)
    return Entities(**{field: values[0] for field, values in ids.items()}, product=match_product(text))


@lru_cache(maxsize=1)
def _claim_reference_res() -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p, re.IGNORECASE) for p in _glossary()["routing"]["claim_reference_patterns"])


def has_claim_reference(text: str) -> bool:
    """A claim ID or a phrase pointing at a particular claim ("my claim", "claim number")."""
    return bool(find_ids(text).get("claim_id")) or any(p.search(text) for p in _claim_reference_res())


def is_follow_up(text: str) -> bool:
    return any(_word_re(p).search(text) for p in _glossary()["follow_up_phrases"])


def is_fast_path(text: str) -> bool:
    """Routing rule 1: exactly one claim ID, a status keyword, ≤ max_words words, no other intent keyword."""
    cfg = _glossary()["fast_path"]
    if len(find_ids(text).get("claim_id", [])) != 1 or len(re.findall(r"\bCLM\d+", text)) != 1:
        return False
    if len(text.split()) > cfg["max_words"]:
        return False
    lowered = text.lower()
    if not any(_word_re(k).search(lowered) for k in cfg["status_keywords"]):
        return False
    return not _other_intent(lowered, cfg["other_intent_keywords"])


def _other_intent(lowered: str, keywords: list[str]) -> bool:
    return any(k in lowered for k in keywords if " " in k) or any(
        re.search(rf"(?<!\w){re.escape(k)}", lowered) for k in keywords if " " not in k
    )


def is_guarantee_only(text: str) -> bool:
    """AC-08-24: a short guarantee request about exactly one claim ID and nothing else (config
    `guarantee_path`; the caller has already matched the guarantee patterns)."""
    cfg = _glossary()["guarantee_path"]
    if len(find_ids(text).get("claim_id", [])) != 1 or len(re.findall(r"\bCLM\d+", text)) != 1:
        return False
    if len(text.split()) > cfg["max_words"]:
        return False
    keywords = [k for k in _glossary()["fast_path"]["other_intent_keywords"] if k not in cfg["allowed"]]
    return not _other_intent(text.lower(), keywords)


def is_greeting(text: str) -> bool:
    """Routing rule 1b: a short hello or thanks made only of greeting words (config `greeting`)."""
    cfg = _glossary()["greeting"]
    words = re.findall(r"[a-z]+", text.lower())
    if not words or len(words) > cfg["max_words"] or re.search(r"\d", text):
        return False
    openers, fillers = set(cfg["openers"]), set(cfg["fillers"])
    return any(w in openers for w in words) and all(w in openers or w in fillers for w in words)


def greeting_plan(text: str) -> Plan:
    return Plan(intents=[Intent(id="i1", type="greeting", sub_question=text.strip())])


def fast_path_plan(text: str, claim_id: str) -> Plan:
    return Plan(
        intents=[
            Intent(
                id="i1", type="claim_status", entities=Entities(claim_id=claim_id), sub_question=text.strip()
            )
        ]
    )
