"""analytics_sql worker, evidence, synthesis and fallback (spec 02 with spec 06)."""

from typing import Any

import pytest
from fakes import install, plan_of

from insurai.agent.runner import analytics_payload, run_turn
from insurai.agent.schemas import ALL_ROWS, TurnResult
from insurai.agent.synthesize import analytics_draft, evidence_blocks
from insurai.agent.workers import ANALYTICS_PROMPT_ROWS, to_evidence
from insurai.api.streaming import final_payload
from insurai.semantic.schemas import SqlDraft, VerifiedQuery
from insurai.tools import analytics
from insurai.tools.analytics import AnalyticsRejected, AnalyticsResult, sql_query_source

SQL = "SELECT policy_type, COUNT(*) AS claims FROM silver.claims GROUP BY 1 LIMIT 200"


def _result(n: int) -> AnalyticsResult:
    return AnalyticsResult(
        sql=SQL,
        columns=["bucket", "claims"],
        rows=[[f"b{i}", 1000 + i] for i in range(n)],
        row_count=n,
        truncated=False,
        chart=None,
        attempts=1,
        sources=[sql_query_source(SQL, "silver.claims")],
    )


@pytest.mark.unit
def test_analytics_evidence_shows_the_prompt_30_rows_and_keeps_all_for_the_ui() -> None:
    ev = to_evidence("i1", "analytics_sql", _result(45))
    assert ev.kind == "AnalyticsResult" and ev.sources[0].label.startswith("[sql:")
    assert len(ev.payload["rows"]) == ANALYTICS_PROMPT_ROWS and len(ev.payload[ALL_ROWS]) == 45
    assert ev.payload["sql"] == SQL and "45 rows" in ev.summary
    block = evidence_blocks([ev])
    assert ALL_ROWS not in block and "b29" in block and "b30" not in block


@pytest.mark.unit
def test_rejection_becomes_a_template_note_without_sources() -> None:
    rejected = AnalyticsRejected(
        reason="forbidden_join", detail="x", sql="SELECT 1", attempts=2, sources=[sql_query_source("x", None)]
    )
    ev = to_evidence("i1", "analytics_sql", rejected)
    assert ev.kind == "unavailable" and ev.sources == []
    assert ev.summary.startswith("I couldn't answer that with a safe, validated query (forbidden join)")
    assert ev.payload["sql"] == "SELECT 1" and ev.payload["attempts"] == 2  # kept for the trace


@pytest.mark.unit
def test_analytics_draft_renders_the_table_with_its_citation() -> None:
    ev = to_evidence("i1", "analytics_sql", _result(33))
    draft = analytics_draft([ev])
    label = ev.sources[0].label
    assert draft.citations == [label]
    assert f"The query returned 33 rows {label}:" in draft.answer_markdown
    assert "| bucket | claims |" in draft.answer_markdown and "| b29 | 1029 |" in draft.answer_markdown
    assert (
        "| b30 |" not in draft.answer_markdown
        and "3 more rows are in the table below." in draft.answer_markdown
    )


@pytest.mark.unit
def test_turn_result_and_final_event_carry_every_row() -> None:
    ev = to_evidence("i1", "analytics_sql", _result(45))
    payload = analytics_payload([ev])
    assert payload is not None and len(payload.rows) == 45 and payload.sql == SQL
    result = TurnResult(thread_id="t", answer_markdown="a", citations=[], trace=[], analytics=payload)
    event = final_payload(result)
    assert event["analytics"]["row_count"] == 45 and len(event["analytics"]["rows"]) == 45
    assert analytics_payload([]) is None


@pytest.fixture
def no_retrieval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        analytics,
        "similar_sql_examples",
        lambda q, k=3: [VerifiedQuery(name="a", question="b", sql=SQL)],
    )


@pytest.mark.integration
@pytest.mark.usefixtures("no_retrieval")
def test_analytics_answer_failing_verification_twice_falls_back_to_the_table(
    graph: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    question = "How many claims per line of business?"
    install(
        monkeypatch,
        {
            "Plan": [plan_of(("analytics", {}), question=question)],
            "SqlDraft": [SqlDraft(sql=SQL, rationale="r")],
            "Text": lambda m: "There are 999,999 claims. [sql:00000000]",  # invented number and label
        },
    )
    result = run_turn(graph, "t-ana-fallback", question, "supervisor")
    outcomes = [e.data["outcome"] for e in result.trace if e.kind == "verify"]
    assert outcomes == ["retry", "abstain"]
    assert not result.answer_markdown.startswith("The policy documents don't address this directly.")
    assert "| policy_type | claims |" in result.answer_markdown and "| Health |" in result.answer_markdown
    assert result.analytics is not None and result.analytics.sql.endswith("LIMIT 200")
    assert result.citations and all(c.startswith("[sql:") for c in result.citations)
    assert "999,999" not in result.answer_markdown


@pytest.mark.integration
@pytest.mark.usefixtures("no_retrieval")
def test_analytics_answer_cites_the_query(graph: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    question = "How many claims per line of business?"
    seen: list[str] = []

    def synth(messages: list[Any]) -> str:
        prompt = str(messages[0].content)
        seen.append(prompt)
        label = prompt.split('source="', 1)[1].split('"', 1)[0]
        return f"Claims split across three lines of business. {label}"

    install(
        monkeypatch,
        {
            "Plan": [plan_of(("analytics", {}), question=question)],
            "SqlDraft": [SqlDraft(sql=SQL, rationale="r")],
            "Text": synth,
        },
    )
    result = run_turn(graph, "t-ana-ok", question, "supervisor")
    assert result.verification_passed is True and result.citations[0].startswith("[sql:")
    assert result.analytics is not None and result.analytics.chart == {
        "type": "bar",
        "x": "policy_type",
        "y": "claims",
    }
    assert ALL_ROWS not in seen[0]


@pytest.mark.integration
@pytest.mark.usefixtures("no_retrieval")
def test_rejected_analytics_answers_from_the_template_without_synthesis(
    graph: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    question = "Average fraud score by customer city via hospitals?"

    def no_synth(messages: list[Any]) -> Any:
        raise AssertionError("the rejection is a template; no synthesis call")

    bad = (
        "SELECT h.city, COUNT(*) FROM silver.customers cu "
        "JOIN silver.hospitals h ON h.city = cu.city GROUP BY 1"
    )
    install(
        monkeypatch,
        {
            "Plan": [plan_of(("analytics", {}), question=question)],
            "SqlDraft": [SqlDraft(sql=bad, rationale="r"), SqlDraft(sql=bad, rationale="r")],
            "Text": no_synth,
        },
    )
    result = run_turn(graph, "t-ana-rejected", question, "claims_agent")
    assert result.answer_markdown.startswith("I couldn't answer that with a safe, validated query")
    assert result.analytics is None


@pytest.mark.integration
@pytest.mark.usefixtures("no_retrieval")
def test_customer_analytics_turn_is_refused(graph: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    question = "What is the approval rate across all customers?"
    install(monkeypatch, {"Plan": [plan_of(("analytics", {}), question=question)]})
    result = run_turn(graph, "t-ana-customer", question, "customer", principal_id="CUST139920")
    # a tool the persona lacks gets the tool-level text, not the row-ownership text (AC-05-10)
    assert "That tool is available to claims agents and supervisors only." in result.answer_markdown
    assert "own account" not in result.answer_markdown and result.analytics is None
