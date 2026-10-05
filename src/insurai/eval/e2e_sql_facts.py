"""End-to-end sql_facts check (reported, not gated): each sql_facts question through the full graph, then a
deterministic test that the normalised gold value appears in the final answer.

Partial evidence for the M4 correctness gate until the spec 11 judge exists. Gold values are recomputed from
the warehouse on every run, as in the tools-only sql_facts slice.
"""

import re
from datetime import date
from decimal import Decimal
from typing import Any

from insurai import db
from insurai.agent import graph as agent_graph
from insurai.agent.checkpoint import memory_saver
from insurai.agent.runner import pending_review, resume, run_turn
from insurai.eval.sql_facts import load_dataset
from insurai.guardrails.verify import number_tokens
from insurai.observability import get_logger
from insurai.rules.schemas import ReviewDecision

log = get_logger(__name__)

SLICE = "e2e_sql_facts"
# Gold "no missing documents": the answer must say so plainly and must not also say something is missing.
NONE_MISSING = re.compile(
    r"\bnot missing\b"
    r"|\bno (?:required )?documents? (?:are|is) missing\b"
    r"|\bno missing documents?\b"
    r"|\bnothing is missing\b"
    r"|\bnone (?:of the (?:required )?documents )?(?:are|is) missing\b"
    r"|\ball required documents (?:are|have been) (?:present|received|submitted|provided)\b"
    r"|\bmissing(?: documents)?\s*:\s*none\b"
)
SAYS_MISSING = re.compile(
    r"\b(?:is|are|still|remains?)\s+missing\b"
    r"|\bmissing(?: documents?)?\s*[:\-]\s*\w"
    r"|\bmissing\s+(?:the|a|an|its|their|your)\b"
)


def states_none_missing(text: str) -> bool:
    """A plain "none missing" statement, and no claim that a document is missing once those are removed."""
    if not NONE_MISSING.search(text):
        return False
    return not SAYS_MISSING.search(NONE_MISSING.sub(" ", text))


def gold_in_answer(gold: Any, answer: str) -> bool | None:
    """Whether the gold value appears in the answer; None when gold is null (not scored)."""
    text = answer.casefold()
    if gold is None:
        return None
    if isinstance(gold, bool):
        return str(gold).casefold() in text
    if isinstance(gold, (int, float, Decimal)):
        value = float(gold)
        norm = str(int(value)) if value == int(value) else repr(value)
        return norm in number_tokens(answer)
    if isinstance(gold, date):
        return gold.isoformat() in answer
    if isinstance(gold, (list, tuple)):
        if not gold:
            return states_none_missing(text)
        return all(str(g).casefold() in text for g in gold)
    return " ".join(str(gold).split()).casefold() in text


def run_slice() -> dict[str, Any]:
    items = load_dataset()
    graph = agent_graph.build_graph(memory_saver())
    rows: list[dict[str, Any]] = []
    with db.connect(read_only=True) as con:
        golds = {i.id: (con.execute(i.gold_sql, i.gold_params).fetchone() or [None])[0] for i in items}
    for item in items:
        thread = f"e2e-{item.id}"
        try:
            result = run_turn(graph, thread, item.turns[0]["content"], item.persona, item.principal_id)
            if pending_review(graph, thread) is not None:
                result = resume(graph, thread, ReviewDecision(action="approve", note="eval auto-approve"))
            answer, error = result.answer_markdown, None
        except Exception as exc:  # scored as a miss
            log.exception("e2e item %s failed", item.id)
            answer, error = "", f"{type(exc).__name__}: {exc}"
        hit = gold_in_answer(golds[item.id], answer)
        rows.append(
            {
                "id": item.id,
                "template": item.tags[0],
                "gold": str(golds[item.id]),
                "hit": hit,
                "answer": answer[:300],
                "error": error,
            }
        )
        log.info("e2e %s hit=%s", item.id, hit)
    scored = [r for r in rows if r["hit"] is not None]
    metrics = {
        "items": len(rows),
        "scored": len(scored),
        "gold_in_answer": round(sum(bool(r["hit"]) for r in scored) / len(scored), 4) if scored else 0.0,
        "misses": [r["id"] for r in scored if not r["hit"]],
    }
    return {"metrics": metrics, "items": rows}
