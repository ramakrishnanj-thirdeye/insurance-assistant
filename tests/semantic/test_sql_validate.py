"""Validator acceptance tests (spec 02): pure AST checks, no warehouse and no LLM."""

import pytest
import sqlglot

from insurai.eval.analytics import load_probes
from insurai.semantic.model import SemanticModel, load_semantic_model
from insurai.semantic.schemas import SqlRejection, ValidatedSql
from insurai.semantic.sql import validate

pytestmark = pytest.mark.unit

PROBES = load_probes()


@pytest.fixture(scope="module")
def model() -> SemanticModel:
    return load_semantic_model()


def _ok(sql: str, persona: str = "supervisor") -> ValidatedSql:
    result = validate(sql, persona, load_semantic_model())  # type: ignore[arg-type]
    assert isinstance(result, ValidatedSql), result
    return result


def test_AC_02_03_probe_file_covers_the_spec_list() -> None:
    ids = {p.id for p in PROBES}
    required = {
        "insert", "update", "delete", "create", "drop", "two_statements", "read_csv", "copy_to", "attach",
        "pragma", "unknown_table", "unknown_column", "logged_customer_join", "customers_hospitals_on_city",
        "fraud_score_as_customer", "getvariable",
    }  # fmt: skip
    assert required <= ids and len(PROBES) >= 15


@pytest.mark.parametrize("probe", PROBES, ids=[p.id for p in PROBES])
def test_AC_02_03_validator_rejects(probe, model: SemanticModel) -> None:  # noqa: ANN001
    result = validate(probe.sql, probe.persona, model)
    assert isinstance(result, SqlRejection), f"{probe.id} passed: {result}"
    assert result.reason == probe.reason, result.detail


@pytest.mark.parametrize(
    "sql",
    [
        "WITH t AS (SELECT policy_type, claim_amount FROM silver.claims) "
        "SELECT policy_type, SUM(claim_amount) FROM t GROUP BY 1",
        "SELECT c.policy_type, COUNT(*) FROM silver.policies p "
        "JOIN silver.claims c ON c.policy_id = p.policy_id GROUP BY 1",  # declared join written right-to-left
        "SELECT d.document_type, COUNT(*) FROM gold.claim_doc_checklist d "
        "JOIN silver.claims c USING (claim_id) WHERE c.policy_type = 'Health' GROUP BY 1",
        "SELECT i.channel, COUNT(*) FROM silver.customer_interactions i JOIN silver.claims c "
        "ON c.claim_id = i.claim_id AND c.policy_type = 'Motor' GROUP BY 1",  # one-table filter inside ON
        "SELECT policy_type FROM silver.claims UNION SELECT policy_type FROM silver.policies",
        "SELECT COUNT(*) FROM silver.claims WHERE customer_id IN (SELECT customer_id FROM silver.customers "
        "WHERE city = 'Pune')",
        "SELECT r.product_name, COUNT(*) FROM gold.rule_results r "
        "JOIN silver.claims c ON c.claim_id = r.claim_id WHERE r.R01 = 'fail' GROUP BY 1",
    ],
)
def test_AC_02_03_allowed_queries_pass(sql: str) -> None:
    _ok(sql)


def test_AC_02_03_join_through_cte_follows_the_column_to_its_table() -> None:
    _ok(
        "WITH p AS (SELECT policy_id, co_pay_pct FROM silver.policies) "
        "SELECT p.co_pay_pct, COUNT(*) FROM silver.claims c JOIN p ON p.policy_id = c.policy_id GROUP BY 1"
    )


def test_AC_02_03_tables_listed_in_order() -> None:
    v = _ok("SELECT COUNT(*) FROM silver.claims c JOIN silver.hospitals h ON h.hospital_id = c.hospital_id")
    assert v.tables == ["silver.claims", "silver.hospitals"]


def test_AC_02_04_limit_injected_when_absent() -> None:
    v = _ok("SELECT claim_status, COUNT(*) FROM silver.claims GROUP BY 1")
    assert v.limit_applied == 200 and v.limit_imposed
    assert sqlglot.parse_one(v.sql, dialect="duckdb").args["limit"].expression.this == "200"


def test_AC_02_04_limit_capped_at_200() -> None:
    v = _ok("SELECT claim_id FROM silver.claims LIMIT 5000")
    assert v.limit_applied == 200 and v.limit_imposed and "LIMIT 200" in v.sql and "5000" not in v.sql


def test_AC_02_04_smaller_limit_kept() -> None:
    v = _ok("SELECT claim_id FROM silver.claims ORDER BY claim_amount DESC LIMIT 5")
    assert v.limit_applied == 5 and not v.limit_imposed and v.sql.endswith("LIMIT 5")


def test_AC_02_04_limit_on_a_union_is_outermost() -> None:
    v = _ok("SELECT city FROM silver.customers UNION SELECT city FROM silver.hospitals")
    assert v.sql.endswith("LIMIT 200")


def test_AC_02_08_claims_agent_customer_name_masked_in_sql() -> None:
    v = _ok(
        "SELECT cu.customer_name, COUNT(*) AS claims FROM silver.claims c "
        "JOIN silver.customers cu ON cu.customer_id = c.customer_id GROUP BY 1",
        "claims_agent",
    )
    assert "UPPER(LEFT(" in v.sql and "AS customer_name" in v.sql
    assert "GROUP BY cu.customer_name" in v.sql  # grouped by the full name, shown as initials


def test_AC_02_08_star_cannot_bypass_masking() -> None:
    v = _ok("SELECT * FROM silver.customers", "claims_agent")
    assert "UPPER(LEFT(" in v.sql


def test_AC_02_08_supervisor_sql_is_unmasked() -> None:
    v = _ok("SELECT customer_name FROM silver.customers", "supervisor")
    assert "UPPER(" not in v.sql


def test_AC_02_08_name_filter_still_uses_the_full_name() -> None:
    v = _ok("SELECT COUNT(*) FROM silver.customers WHERE customer_name = 'Arjun Sharma'", "claims_agent")
    assert "'Arjun Sharma'" in v.sql and "UPPER(" not in v.sql


def test_ambiguous_column_detail_names_both_tables() -> None:
    result = validate(
        "SELECT policy_type, COUNT(*) FROM silver.claims c "
        "JOIN silver.policies p ON p.policy_id = c.policy_id "
        "GROUP BY 1",
        "supervisor",
        load_semantic_model(),
    )
    assert isinstance(result, SqlRejection) and result.reason == "unknown_column"
    assert "ambiguous" in result.detail and "silver.claims and silver.policies" in result.detail


def test_wrong_alias_detail_names_the_table_that_has_the_column() -> None:
    result = validate(
        "SELECT c.customer_name FROM silver.claims c "
        "JOIN silver.customers cu ON cu.customer_id = c.customer_id",
        "supervisor",
        load_semantic_model(),
    )
    assert isinstance(result, SqlRejection) and result.reason == "unknown_column"
    assert "'customer_name' is a column of silver.customers" in result.detail
