"""Few-shot hygiene: no prompt in config/prompts may contain golden-set IDs or near-identical phrasing."""

import json
import re
from pathlib import Path

import pytest
from rapidfuzz import fuzz

from insurai.agent.prompts import PROMPTS_DIR, load_prompt
from insurai.settings import ROOT

pytestmark = pytest.mark.unit

ID_RE = re.compile(r"\b(?:CLM|POL|CUST|HOSP)\d+\b")
NEAR = 85  # rapidfuzz ratio at or above this counts as the same phrasing
PROMPTS = sorted(PROMPTS_DIR.glob("*.md"))


def _golden_questions() -> list[tuple[str, str]]:
    out = []
    for path in sorted((ROOT / "eval" / "datasets").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                # A `ref` row (eval/datasets/guardrails.jsonl) reuses an item checked in its own dataset.
                out += [(item["id"], t["content"]) for t in item.get("turns", [])]
    return out


def _examples(body: str) -> list[str]:
    return re.findall(r'^- "([^"]+)"', body, flags=re.MULTILINE)


def _lines(body: str) -> list[str]:
    """Quoted examples plus every non-heading prose line: anything a model could copy from."""
    prose = [ln.strip().lstrip("-*0123456789. ") for ln in body.splitlines()]
    return _examples(body) + [ln for ln in prose if ln and not ln.startswith(("#", "<", "---"))]


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w ]", " ", ID_RE.sub("<id>", text.lower())).split())


def _contains(line: str, question: str) -> bool:
    """A golden question copied into a line; one- or two-word questions ("Thanks!") match whole lines."""
    return len(question.split()) >= 3 and question in line


def test_every_prompt_file_is_checked() -> None:
    assert {p.stem for p in PROMPTS} >= {"planner", "synthesize", "templates", "text_to_sql"}


@pytest.mark.parametrize("path", PROMPTS, ids=lambda p: p.stem)
def test_prompt_shares_no_ids_with_the_golden_set(path: Path) -> None:
    prompt_ids = set(ID_RE.findall(path.read_text(encoding="utf-8")))
    leaks = {(item_id, i) for item_id, q in _golden_questions() for i in ID_RE.findall(q) if i in prompt_ids}
    assert not leaks


@pytest.mark.parametrize("path", PROMPTS, ids=lambda p: p.stem)
def test_prompt_does_not_copy_golden_phrasing(path: Path) -> None:
    candidates = [n for n in (_norm(x) for x in _lines(load_prompt(path.stem).body)) if len(n.split()) >= 3]
    leaks = [
        (item_id, question, line)
        for item_id, question in _golden_questions()
        for line in candidates
        if (q := _norm(question)) and (_contains(line, q) or line in q or fuzz.ratio(q, line) >= NEAR)
    ]
    assert not leaks


def _verified_questions() -> list[tuple[str, str]]:
    """The semantic model's verified queries: rendered into text_to_sql as retrieved few-shots (spec 02)."""
    from insurai.semantic.model import SemanticModel

    return [(q.name, q.question) for q in SemanticModel.load().verified_queries]


def _analytics_questions() -> list[tuple[str, str]]:
    return [(item_id, q) for item_id, q in _golden_questions() if item_id.startswith("ANA")]


def test_analytics_golden_set_is_checked() -> None:
    assert len(_analytics_questions()) == 15


def test_analytics_questions_share_no_ids_with_verified_queries() -> None:
    verified_ids = {i for _, q in _verified_questions() for i in ID_RE.findall(q)}
    verified_ids |= {i for q in _verified_sql() for i in ID_RE.findall(q)}
    assert not [
        (item_id, i) for item_id, q in _analytics_questions() for i in ID_RE.findall(q) if i in verified_ids
    ]


def _verified_sql() -> list[str]:
    from insurai.semantic.model import SemanticModel

    return [q.sql for q in SemanticModel.load().verified_queries]


def test_analytics_questions_do_not_copy_verified_queries() -> None:
    """The few-shot examples the generator sees must not be near-copies of what the eval asks."""
    leaks = [
        (item_id, name)
        for item_id, question in _analytics_questions()
        for name, verified in _verified_questions()
        if (q := _norm(question))
        and (v := _norm(verified))
        and (_contains(v, q) or _contains(q, v) or fuzz.ratio(q, v) >= NEAR)
    ]
    assert not leaks


def test_planner_has_enough_few_shot_examples() -> None:
    assert len(_examples(load_prompt("planner").body)) >= 15  # spec 06: 15+ few-shot examples


def _routing_terms() -> list[str]:
    """Every literal entry of config/glossary.yaml `routing` (words and promote_to_analysis)."""
    from insurai.agent.resolve import _glossary

    routing = _glossary()["routing"]
    terms = [w for spec in routing["intent_triggers"].values() for w in spec.get("words", [])]
    return terms + list(routing["promote_to_analysis"])


def test_routing_triggers_do_not_copy_golden_phrasing() -> None:
    """Trigger lists come from intent definitions and the glossary, not eval items (spec 06 rule 9): a
    multi-word trigger may appear verbatim in an eval question only when a glossary synonym group has it."""
    from insurai.retrieval.glossary import load_glossary

    synonyms = {t.casefold() for group in load_glossary().synonyms for t in group}
    multi = [t.rstrip("*") for t in _routing_terms() if len(t.split()) > 1]
    leaks = [
        (item_id, term)
        for term in multi
        if term.casefold() not in synonyms
        for item_id, question in _golden_questions()
        if re.search(rf"(?<!\w){re.escape(term)}", question, re.IGNORECASE)
    ]
    assert not leaks
