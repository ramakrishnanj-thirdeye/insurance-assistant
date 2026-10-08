"""Execution tests against the real warehouse (spec 02)."""

import re
import time

import pytest

from insurai.semantic.model import load_semantic_model
from insurai.semantic.schemas import QueryResult, SqlRejection, ValidatedSql
from insurai.semantic.sql import execute, validate
from insurai.settings import get_settings

pytestmark = pytest.mark.integration

MODEL = load_semantic_model()


@pytest.fixture(autouse=True)
def warehouse_ready() -> None:
    if not get_settings().paths.warehouse.exists():
        pytest.skip("data/warehouse.duckdb not built: run `make data`")


def _run(sql: str, persona: str = "supervisor") -> QueryResult:
    v = validate(sql, persona, MODEL)  # type: ignore[arg-type]
    assert isinstance(v, ValidatedSql), v
    result = execute(v, get_settings().sql.timeout_s)
    assert isinstance(result, QueryResult), result
    return result


@pytest.mark.parametrize("query", MODEL.verified_queries, ids=[q.name for q in MODEL.verified_queries])
def test_AC_02_02_verified_queries_validate_and_return_rows(query) -> None:  # noqa: ANN001
    result = _run(query.sql)
    assert result.row_count >= 1


def test_AC_02_02_paid_in_full_despite_copay_reproduces_20903() -> None:
    query = next(q for q in MODEL.verified_queries if q.name == "approved_paid_in_full_despite_copay")
    assert _run(query.sql).rows == [[20903]]


def test_AC_02_02_rule_results_queries_are_supervisor_only() -> None:
    for name in ("approved_outside_policy_period", "maternity_paid_where_excluded_by_product"):
        query = next(q for q in MODEL.verified_queries if q.name == name)
        rejection = validate(query.sql, "claims_agent", MODEL)
        assert isinstance(rejection, SqlRejection) and rejection.reason == "persona"


def test_AC_02_06_cross_join_interrupted_returns_timeout() -> None:
    cross = ValidatedSql(
        sql="SELECT COUNT(*) FROM silver.claims CROSS JOIN gold.claim_doc_checklist "
        "WHERE claims.claim_amount + claim_doc_checklist.required::INT > 0",
        tables=["silver.claims", "gold.claim_doc_checklist"],
        limit_applied=200,
    )
    start = time.perf_counter()
    result = execute(cross, timeout_s=1)
    assert isinstance(result, SqlRejection) and result.reason == "timeout"
    assert time.perf_counter() - start < 5


def test_execute_disables_external_access_behind_the_validator() -> None:
    raw = ValidatedSql(sql="SELECT * FROM read_csv('pyproject.toml')", tables=[], limit_applied=200)
    result = execute(raw, timeout_s=5)
    assert isinstance(result, SqlRejection) and result.reason == "runtime"


def test_execute_reports_runtime_errors() -> None:
    bad = ValidatedSql(
        sql="SELECT 1 / 'x'::INT FROM silver.claims", tables=["silver.claims"], limit_applied=200
    )
    result = execute(bad, timeout_s=5)
    assert isinstance(result, SqlRejection) and result.reason == "runtime"


def test_AC_02_08_claims_agent_customer_name_masked() -> None:
    result = _run(
        "SELECT cu.customer_name, c.claim_amount FROM silver.claims c "
        "JOIN silver.customers cu ON cu.customer_id = c.customer_id ORDER BY c.claim_amount DESC LIMIT 5",
        "claims_agent",
    )
    assert result.columns == ["customer_name", "claim_amount"]
    assert all(re.fullmatch(r"([A-Z]\. )*[A-Z]\.", row[0]) for row in result.rows), result.rows


def test_AC_02_08_supervisor_sees_full_name() -> None:
    result = _run(
        "SELECT cu.customer_name FROM silver.claims c "
        "JOIN silver.customers cu ON cu.customer_id = c.customer_id ORDER BY c.claim_amount DESC LIMIT 1"
    )
    name = result.rows[0][0]
    assert " " in name and not name.endswith(".")


def test_result_is_json_safe_with_kinds_and_truncation() -> None:
    result = _run(
        "SELECT date_trunc('month', claim_date) AS month, ROUND(AVG(claim_amount), 2) AS avg_amount "
        "FROM silver.claims GROUP BY 1 ORDER BY 1"
    )
    assert result.column_kinds == ["temporal", "numeric"]
    assert isinstance(result.rows[0][0], str) and isinstance(result.rows[0][1], float)
    assert not result.truncated  # 46 months, under the row limit
    many = _run("SELECT claim_id FROM silver.claims")
    assert many.row_count == 200 and many.truncated
