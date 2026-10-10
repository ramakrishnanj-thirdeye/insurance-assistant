"""Answer correctness (spec 11): the judge role scores an answer against the gold answer on a 1–5 rubric
(judge_correctness.md); a score of 4 or more counts as correct.

Runs in phase 2, after every answer of a slice exists, so a local Ollama loads the judge once. Rows keep
`judge_score` and `judge_reason`; per-item scores are never logged (judge calibration keeps them sealed
until the human scores are in, eval/calibration.py).
"""

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, field_validator

from insurai.agent.prompts import load_prompt
from insurai.eval.stats import prop
from insurai.llm.structured import structured_call
from insurai.observability import get_logger

log = get_logger(__name__)

CORRECT_MIN = 4
JUDGE_INSTRUCTION = "Score the answer."


class CorrectnessScore(BaseModel):
    """A score with a non-empty reason: an empty or blank reason fails validation, so `structured_call`
    retries once with the error as feedback; a second failure is recorded as judge_error (never scored)."""

    score: int = Field(ge=1, le=5)
    reason: str = Field(min_length=1)

    @field_validator("reason", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


def judge_correctness(question: str, gold: str, answer: str) -> CorrectnessScore:
    prompt = load_prompt("judge_correctness")
    system = prompt.render(question=question, gold_answer=gold, answer=answer)
    messages = [SystemMessage(system), HumanMessage(JUDGE_INSTRUCTION)]
    score, _ = structured_call("judge", CorrectnessScore, messages, prompt.id, prompt.version)
    return score


def judge_rows(
    rows: list[dict[str, Any]], golds: dict[str, tuple[str, str]], answer_key: str = "answer"
) -> None:
    """Add judge_score and judge_reason to each row with a gold (question, gold answer) and an answer; an
    item without an answer scores 1 (no judge call); a judge failure is recorded as judge_error."""
    for row in rows:
        if row["id"] not in golds:
            continue
        question, gold = golds[row["id"]]
        answer = row.get(answer_key) or ""
        if not answer.strip():
            row |= {"judge_score": 1, "judge_reason": "no answer"}
            continue
        try:
            scored = judge_correctness(question, gold, answer)
        except Exception as exc:  # one failing judge call must not sink the slice
            log.exception("correctness judge failed on %s", row["id"])
            row["judge_error"] = f"{type(exc).__name__}: {exc}"
            continue
        row |= {"judge_score": scored.score, "judge_reason": scored.reason}


def correctness_metrics(rows: list[dict[str, Any]], counts: dict[str, list[int]]) -> dict[str, Any]:
    """Correctness over judged rows only; rows with a judge_error are excluded and counted separately."""
    scored = [r for r in rows if isinstance(r.get("judge_score"), int)]
    out: dict[str, Any] = {}
    prop(out, counts, "correctness", sum(r["judge_score"] >= CORRECT_MIN for r in scored), len(scored))
    out["judge_errors"] = sum("judge_error" in r for r in rows)
    return out


def is_correct(row: dict[str, Any]) -> bool | None:
    score = row.get("judge_score")
    return score >= CORRECT_MIN if isinstance(score, int) else None
