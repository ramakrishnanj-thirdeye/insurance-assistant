"""run_analytics (spec 02): access, repair loop, rejection, citation. Scripted generator; examples and
execution are stubbed except in the integration test."""

from typing import Any

import pytest
from fakes import forbid_llm, install
from langchain_core.messages import BaseMessage
from tool_ids import make_ctx

from insurai.semantic.schemas import QueryResult, SqlDraft, SqlRejection, VerifiedQuery
from insurai.settings import get_settings
from insurai.tools import analytics
from insurai.tools.analytics import AnalyticsRejected, AnalyticsResult, sql_query_source
from insurai.tools.registry import TOOLS
from insurai.tools.schemas import AccessDenied
from insurai.tools.sources import label_regexes

GOOD = "SELECT policy_type, COUNT(*) AS claims FROM silver.claims GROUP BY 1"
RESULT = QueryResult(
    columns=["policy_type", "claims"],
    rows=[["Health", 3], ["Motor", 2]],
    row_count=2,
    truncated=False,
    column_kinds=["text", "numeric"],
)


@pytest.fixture
def no_retrieval(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    asked: list[str] = []

    def fake(question: str, k: int = 3) -> list[VerifiedQuery]:
        asked.append(question)
        return [
            VerifiedQuery(name="a", question="claims by type", sql=GOOD),
            VerifiedQuery(name="rr", question="rules", sql="SELECT COUNT(*) FROM gold.rule_results WHERE C1"),
        ]

    monkeypatch.setattr(analytics, "similar_sql_examples", fake)
    return asked


@pytest.fixture
def executed(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    ran: list[str] = []

    def fake(v: Any, timeout_s: float) -> QueryResult | SqlRejection:
        ran.append(v.sql)
        return RESULT

    monkeypatch.setattr(analytics, "execute", fake)
    return ran


def _drafts(*sqls: str) -> list[SqlDraft]:
    return [SqlDraft(sql=s, rationale="r") for s in sqls]


@pytest.mark.unit
@pytest.mark.usefixtures("no_retrieval")
def test_AC_02_05_customer_run_analytics_denied_without_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    forbid_llm(monkeypatch)
    result = TOOLS["run_analytics"](make_ctx("customer", "CUST139920"), "approval rate by line of business")
    assert isinstance(result, AccessDenied)


@pytest.mark.unit
@pytest.mark.usefixtures("no_retrieval")
def test_first_attempt_success_returns_sql_rows_chart_and_citation(
    monkeypatch: pytest.MonkeyPatch, executed: list[str]
) -> None:
    install(monkeypatch, {"SqlDraft": _drafts(GOOD)})
    result = TOOLS["run_analytics"](make_ctx("supervisor"), "claims per line of business")
    assert isinstance(result, AnalyticsResult)
    assert result.attempts == 1 and result.rows == RESULT.rows and result.sql == executed[0]
    assert result.sql.endswith("LIMIT 200")
    assert result.chart is not None and (result.chart.type, result.chart.x) == ("bar", "policy_type")
    (source,) = result.sources
    assert source.kind == "sql" and source.table == "silver.claims"
    assert source.label == f"[sql:{source.key}]" and len(source.key or "") == 8


@pytest.mark.unit
@pytest.mark.usefixtures("no_retrieval", "executed")
def test_repair_succeeds_on_the_second_attempt_with_the_error_text(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts: list[str] = []
    drafts = _drafts("SELECT claim_ref FROM silver.claims", GOOD)

    def reply(messages: list[BaseMessage]) -> SqlDraft:
        prompts.append(str(messages[-1].content))
        return drafts.pop(0)

    install(monkeypatch, {"SqlDraft": reply})
    result = TOOLS["run_analytics"](make_ctx("claims_agent"), "claims per line of business")
    assert isinstance(result, AnalyticsResult) and result.attempts == 2
    assert "<previous_error>(none)</previous_error>" in prompts[0]
    assert "unknown_column" in prompts[1] and "claim_ref" in prompts[1]


@pytest.mark.unit
@pytest.mark.usefixtures("no_retrieval", "executed")
def test_second_failure_returns_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    install(
        monkeypatch, {"SqlDraft": _drafts("SELECT nope FROM silver.claims", "SELECT * FROM silver.payments")}
    )
    result = TOOLS["run_analytics"](make_ctx("supervisor"), "q")
    assert isinstance(result, AnalyticsRejected)
    assert (result.reason, result.attempts) == ("unknown_table", 2)
    assert result.sql == "SELECT * FROM silver.payments"


@pytest.mark.unit
@pytest.mark.usefixtures("no_retrieval", "executed")
@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("DELETE FROM silver.claims", "not_select"),
        ("SELECT getvariable('as_of')", "forbidden_function"),
        ("SELECT COUNT(*) FROM gold.rule_results", "persona"),
    ],
)
def test_unsafe_sql_is_not_repaired(monkeypatch: pytest.MonkeyPatch, sql: str, reason: str) -> None:
    install(monkeypatch, {"SqlDraft": _drafts(sql)})  # a second generator call would fail: list is empty
    result = TOOLS["run_analytics"](make_ctx("claims_agent"), "q")
    assert isinstance(result, AnalyticsRejected) and (result.reason, result.attempts) == (reason, 1)


@pytest.mark.unit
@pytest.mark.usefixtures("no_retrieval")
def test_timeout_is_not_repaired(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analytics, "execute", lambda v, t: SqlRejection(reason="timeout", detail="slow"))
    install(monkeypatch, {"SqlDraft": _drafts(GOOD)})
    result = TOOLS["run_analytics"](make_ctx("supervisor"), "q")
    assert isinstance(result, AnalyticsRejected) and (result.reason, result.attempts) == ("timeout", 1)


@pytest.mark.unit
@pytest.mark.usefixtures("no_retrieval")
def test_runtime_error_gets_one_repair(monkeypatch: pytest.MonkeyPatch) -> None:
    outcomes: list[QueryResult | SqlRejection] = [
        SqlRejection(reason="runtime", detail="Conversion Error"),
        RESULT,
    ]
    monkeypatch.setattr(analytics, "execute", lambda v, t: outcomes.pop(0))
    install(monkeypatch, {"SqlDraft": _drafts(GOOD, GOOD)})
    result = TOOLS["run_analytics"](make_ctx("supervisor"), "q")
    assert isinstance(result, AnalyticsResult) and result.attempts == 2


@pytest.mark.unit
@pytest.mark.usefixtures("executed")
def test_examples_the_persona_cannot_run_are_dropped(
    monkeypatch: pytest.MonkeyPatch, no_retrieval: list[str]
) -> None:
    prompts: list[str] = []

    def reply(messages: list[BaseMessage]) -> SqlDraft:
        prompts.append(str(messages[-1].content))
        return SqlDraft(sql=GOOD, rationale="r")

    install(monkeypatch, {"SqlDraft": reply})
    TOOLS["run_analytics"](make_ctx("claims_agent"), "q")
    TOOLS["run_analytics"](make_ctx("supervisor"), "q")
    assert "gold.rule_results" not in prompts[0]  # neither the example nor the model context
    assert "gold.rule_results WHERE C1" in prompts[1]


@pytest.mark.unit
def test_sql_label_passes_the_citation_regex() -> None:
    sql_regex, _ = label_regexes()
    label = sql_query_source("SELECT 1", "silver.claims").label
    assert sql_regex.fullmatch(label)
    assert sql_regex.fullmatch("[claims:CLM300210]")  # row labels unchanged


@pytest.mark.unit
def test_AC_05_01_run_analytics_persona_gate() -> None:
    from insurai.tools import access

    assert access.tool_allowed(make_ctx("claims_agent"), "run_analytics")
    assert access.tool_allowed(make_ctx("supervisor"), "run_analytics")
    assert not access.tool_allowed(make_ctx("customer", "CUST139920"), "run_analytics")


@pytest.mark.integration
@pytest.mark.usefixtures("no_retrieval")
def test_AC_02_08_run_analytics_masks_names_for_claims_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    if not get_settings().paths.warehouse.exists():
        pytest.skip("data/warehouse.duckdb not built: run `make data`")
    sql = (
        "SELECT cu.customer_name, c.claim_amount FROM silver.claims c JOIN silver.customers cu "
        "ON cu.customer_id = c.customer_id ORDER BY c.claim_amount DESC LIMIT 3"
    )
    install(monkeypatch, {"SqlDraft": _drafts(sql, sql)})
    agent = TOOLS["run_analytics"](make_ctx("claims_agent"), "names on the largest claims")
    boss = TOOLS["run_analytics"](make_ctx("supervisor"), "names on the largest claims")
    assert isinstance(agent, AnalyticsResult) and isinstance(boss, AnalyticsResult)
    assert [r[1] for r in agent.rows] == [r[1] for r in boss.rows]
    for masked, full in zip(agent.rows, boss.rows, strict=True):
        assert masked[0] == " ".join(f"{w[0].upper()}." for w in full[0].split())  # "A. S."
