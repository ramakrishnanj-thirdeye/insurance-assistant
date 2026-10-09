"""V7 in the eval (spec 08, spec 11): the groundedness judge over any slice that produces full answers.

A slice keeps, per row, the answer text and the intent types, and holds the evidence aside (it is not
written to the report). After every answer is generated (phase 1), `judge_rows` runs the judge on each
row with a V7 intent (phase 2), so a local Ollama loads the judge once instead of swapping models on
every item (ADR-006 amendment). `v7_metrics` summarises the rows. The full-suite policy_clauses and
comparison e2e slices (M7b) reuse both.
"""

from typing import Any

from insurai.agent.schemas import Evidence
from insurai.guardrails.groundedness import V7_INTENTS, judge_groundedness
from insurai.guardrails.verify import v7_outcome
from insurai.observability import get_logger

log = get_logger(__name__)


def judge_rows(
    rows: list[dict[str, Any]],
    evidence: dict[str, list[Evidence]],
    answer_key: str = "answer",
    intents_key: str = "intents",
) -> None:
    """Add v7_passed, v7_detail and v7_unsupported to each judged row in place (v7_error on a failure)."""
    for row in rows:
        ev = evidence.get(row["id"])
        if ev is None or not row.get(answer_key) or not V7_INTENTS & set(row.get(intents_key) or []):
            continue
        try:
            verdict, _ = judge_groundedness(row[answer_key], ev)
        except Exception as exc:  # one failing judge call must not sink the slice
            log.exception("V7 judge failed on %s", row["id"])
            row["v7_error"] = f"{type(exc).__name__}: {exc}"
            continue
        outcome, unsupported = v7_outcome(verdict)
        row |= {"v7_passed": outcome.passed, "v7_detail": outcome.detail, "v7_unsupported": unsupported}


def v7_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    judged = [r for r in rows if "v7_passed" in r]
    return {
        "v7_judged": len(judged),
        "v7_pass_rate": round(sum(r["v7_passed"] for r in judged) / len(judged), 4) if judged else None,
        "v7_unsupported_total": sum(len(r["v7_unsupported"]) for r in judged),
        "v7_errors": sum("v7_error" in r for r in rows),
    }


def verifier_pass_rates(rows: list[dict[str, Any]], key: str = "checks") -> dict[str, float]:
    """Per check (V1..V7), the share of rows whose final verify event passed it; skipped checks excluded."""
    seen: dict[str, list[bool]] = {}
    for row in rows:
        for check in row.get(key) or []:
            if not check.get("skipped"):
                seen.setdefault(check["check"], []).append(bool(check["passed"]))
    return {k: round(sum(v) / len(v), 4) for k, v in sorted(seen.items())}


def final_checks(trace: list[Any]) -> list[dict[str, Any]]:
    """The checks of the turn's last verify event (after any retry)."""
    events = [e for e in trace if e.kind == "verify"]
    return list(events[-1].data.get("checks", [])) if events else []
