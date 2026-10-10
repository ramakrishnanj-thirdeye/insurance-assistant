"""Faithfulness over code-split claims (spec 11, AC-11-23): the headline counts verbatim and judged claims,
the diagnostic judged claims only; a failed batch is excluded and counted, a failed judge is a judge error."""

from typing import Any

import pytest
from fakes import install, verdicts

from insurai.agent.schemas import Evidence
from insurai.eval.groundedness import judge_rows, v7_metrics
from insurai.tools.schemas import SourceRef

pytestmark = pytest.mark.unit

VERBATIM = "Illegal use, racing, breakdown unrelated to accident."
CLAIMS = [f"Clause {n} applies to the claim." for n in range(1, 21)]


def _ev() -> list[Evidence]:
    ref = SourceRef(kind="policy", label="[Car Shield Plus §9 Exclusions]")
    return [
        Evidence(
            intent_id="i1",
            worker="w",
            kind="RetrievalResult",
            payload={"clauses": [{"text": VERBATIM}]},
            sources=[ref],
            summary="",
        )
    ]


def test_AC_11_23_faithfulness_headline_and_judged_with_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, {"ClaimVerdicts": verdicts(lambda claim: claim != "Dental is covered.")})
    rows = [
        {
            "id": "P1",
            "answer": f"{VERBATIM} Racing is excluded. Dental is covered.",
            "intents": ["policy_question"],
        }
    ]
    judge_rows(rows, {"P1": _ev()})
    assert (rows[0]["v7_claims"], rows[0]["v7_supported"], rows[0]["v7_verbatim"]) == (2, 1, 1)
    counts: dict[str, list[int]] = {}
    m = v7_metrics(rows, counts)
    assert counts["faithfulness"] == [2, 3] and counts["faithfulness_judged"] == [1, 2]
    assert m["faithfulness"] == 0.6667 and m["faithfulness_judged"] == 0.5
    assert counts["v7_verbatim_share"] == [1, 3] and m["v7_claims_total"] == 3


def test_AC_11_23_failed_batch_is_excluded_and_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = iter([None, {"verdicts": []}, {"verdicts": []}, None])

    def judge(messages: list[Any]) -> Any:
        reply = next(calls)
        return verdicts()(messages) if reply is None else reply

    install(monkeypatch, {"ClaimVerdicts": judge})
    rows = [{"id": "P1", "answer": " ".join(CLAIMS), "intents": ["policy_question"]}]
    judge_rows(rows, {"P1": _ev()})
    assert rows[0]["v7_excluded"] == 8 and rows[0]["v7_claims"] == 12 and rows[0]["v7_passed"]
    assert "8 claim(s) not judged" in rows[0]["v7_detail"]
    counts: dict[str, list[int]] = {}
    m = v7_metrics(rows, counts)
    assert counts["faithfulness"] == [12, 12] and counts["faithfulness_judged"] == [12, 12]
    assert m["v7_excluded_total"] == 8 and m["v7_judge_errors"] == 0


def test_AC_11_23_judge_failing_every_batch_is_a_judge_error(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, {"ClaimVerdicts": lambda m: {"verdicts": []}})
    rows = [{"id": "P1", "answer": "Racing is excluded. Dental is covered.", "intents": ["policy_question"]}]
    judge_rows(rows, {"P1": _ev()})
    assert "v7_judge_error" in rows[0] and "v7_passed" not in rows[0]
    counts: dict[str, list[int]] = {}
    m = v7_metrics(rows, counts)
    assert m["v7_judge_errors"] == 1 and m["v7_judged"] == 0 and counts["faithfulness"] == [0, 0]
