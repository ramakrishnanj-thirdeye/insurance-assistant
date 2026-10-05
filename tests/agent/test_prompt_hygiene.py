"""Few-shot hygiene: planner.md must not contain golden-set questions, IDs or near-identical phrasing."""

import json
import re

import pytest
from rapidfuzz import fuzz

from insurai.agent.prompts import load_prompt
from insurai.settings import ROOT

pytestmark = pytest.mark.unit

ID_RE = re.compile(r"\b(?:CLM|POL|CUST|HOSP)\d+\b")
NEAR = 85  # rapidfuzz ratio at or above this counts as the same phrasing


def _golden_questions() -> list[tuple[str, str]]:
    out = []
    for path in sorted((ROOT / "eval" / "datasets").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                out += [(item["id"], t["content"]) for t in item["turns"]]
    return out


def _examples() -> list[str]:
    return re.findall(r'^- "([^"]+)"', load_prompt("planner").body, flags=re.MULTILINE)


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w ]", " ", ID_RE.sub("<id>", text.lower())).split())


def test_planner_examples_share_no_ids_with_the_golden_set() -> None:
    prompt_ids = set(ID_RE.findall(load_prompt("planner").body))
    leaks = {(item_id, i) for item_id, q in _golden_questions() for i in ID_RE.findall(q) if i in prompt_ids}
    assert not leaks


def test_planner_examples_do_not_copy_golden_phrasing() -> None:
    examples = [_norm(e) for e in _examples()]
    assert len(examples) >= 15  # spec 06: 15+ few-shot examples
    leaks = [
        (item_id, question, example)
        for item_id, question in _golden_questions()
        for example in examples
        if (q := _norm(question)) and (q in example or example in q or fuzz.ratio(q, example) >= NEAR)
    ]
    assert not leaks
