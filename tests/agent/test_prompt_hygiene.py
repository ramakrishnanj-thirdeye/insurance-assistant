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
                out += [(item["id"], t["content"]) for t in item["turns"]]
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
    assert {p.stem for p in PROMPTS} >= {"planner", "synthesize", "templates"}


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


def test_planner_has_enough_few_shot_examples() -> None:
    assert len(_examples(load_prompt("planner").body)) >= 15  # spec 06: 15+ few-shot examples
