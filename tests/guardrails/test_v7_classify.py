"""V7 classifies code-split claims (spec 08, AC-08-22): the judge gets numbered claims in batches and answers
one verdict per number; it never extracts claims of its own."""

from typing import Any

import pytest
from fakes import install, judge_claims, verdicts

from insurai.guardrails.groundedness import judge_groundedness, verdict_schema
from insurai.llm.structured import StructuredOutputError

pytestmark = pytest.mark.unit

CLAIMS = [f"Clause {n} applies to the claim." for n in range(1, 21)]


def _scripted(monkeypatch: pytest.MonkeyPatch, replies: list[Any]) -> list[list[str]]:
    """Judge calls in order: a reply of None answers with full verdicts, any other value is returned as is."""
    seen: list[list[str]] = []

    def judge(messages: list[Any]) -> Any:
        seen.append(judge_claims(messages))
        reply = replies.pop(0) if replies else None
        return verdicts()(messages) if reply is None else reply

    install(monkeypatch, {"ClaimVerdicts": judge})
    return seen


def test_AC_08_22_v7_sends_only_code_split_claims_numbered(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def judge(messages: list[Any]) -> dict[str, Any]:
        seen.append(str(messages[0].content))
        return {"verdicts": [{"n": 2, "supported": False}, {"n": 1, "supported": True}]}

    install(monkeypatch, {"ClaimVerdicts": judge})
    answer = "Next steps:\n- Racing is excluded [Car Shield Plus §9 Exclusions].\n- Dental is covered."
    verdict, calls = judge_groundedness(answer, [])
    assert "<claims>\n1. Racing is excluded.\n2. Dental is covered.\n</claims>" in seen[0]
    assert [(c.text, c.supported, c.settled_by) for c in verdict.claims] == [
        ("Racing is excluded.", True, "judge"),
        ("Dental is covered.", False, "judge"),
    ]
    assert len(calls) == 1 and verdict.judge_errors == []


def test_AC_08_22_v7_empty_verdicts_are_retried_once(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _scripted(monkeypatch, [{"verdicts": []}, None])
    verdict, calls = judge_groundedness("Racing is excluded. Dental is covered.", [])
    assert len(seen) == 2 and calls[0].attempts == 2
    assert all(c.supported for c in verdict.claims) and len(verdict.claims) == 2


def test_AC_08_22_v7_incomplete_verdicts_twice_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    partial = {"verdicts": [{"n": 1, "supported": True}]}
    _scripted(monkeypatch, [partial, partial])
    with pytest.raises(StructuredOutputError):
        judge_groundedness("Racing is excluded. Dental is covered.", [])


def test_AC_08_22_v7_no_claims_left_makes_no_call(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _scripted(monkeypatch, [])
    verdict, calls = judge_groundedness("Next steps:\n| A | B |\n|---|---|", [])
    assert seen == [] and calls == [] and verdict.claims == []


def test_AC_08_22_v7_twenty_claims_three_batches_one_failing(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _scripted(monkeypatch, [None, {"verdicts": []}, {"verdicts": []}, None])
    verdict, calls = judge_groundedness(" ".join(CLAIMS), [])
    assert [len(batch) for batch in seen] == [8, 8, 8, 4]  # batch 2 sent twice (one retry)
    assert seen[1] == seen[2] == CLAIMS[8:16]
    assert len(calls) == 2  # the failed batch has no completed call
    assert verdict.judge_errors == CLAIMS[8:16]
    assert [c.text for c in verdict.claims] == CLAIMS[:8] + CLAIMS[16:]


def test_AC_08_22_verdict_schema_ignores_extra_and_repeated_numbers() -> None:
    schema = verdict_schema(2)
    ok = schema.model_validate(
        {"verdicts": [{"n": 1, "supported": True}, {"n": 1, "supported": False}, {"n": 2, "supported": True}]}
    )
    assert schema.__name__ == "ClaimVerdicts" and len(ok.verdicts) == 3
    with pytest.raises(ValueError, match="missing \\[2\\]"):
        schema.model_validate({"verdicts": [{"n": 1, "supported": True}, {"n": 3, "supported": True}]})
