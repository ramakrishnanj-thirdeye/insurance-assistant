from pathlib import Path

import duckdb
import pytest
import yaml
from pydantic import ValidationError

from insurai.semantic.model import SEMANTIC_MODEL_FILE, SemanticModel
from insurai.settings import get_settings

VERIFIED = 17  # 14 from spec 04 + 3 supervisor/co-pay queries added with spec 02 (2026-10-08)


@pytest.mark.unit
def test_verified_queries_load_for_sql_examples() -> None:
    model = SemanticModel.load()
    assert len(model.verified_queries) == VERIFIED
    assert len({q.name for q in model.verified_queries}) == VERIFIED
    assert all(q.question and q.sql.lstrip().upper().startswith("SELECT") for q in model.verified_queries)


@pytest.mark.unit
def test_AC_02_01_model_loads_and_validates() -> None:
    model = SemanticModel.load()
    assert set(model.allowed_tables()) == {
        "claims", "policies", "customers", "hospitals", "claim_documents", "interactions", "rule_results",
    }  # fmt: skip
    assert model.allowed_tables()["claim_documents"] == "gold.claim_doc_checklist"
    assert frozenset({("interactions", "claim_id"), ("claims", "claim_id")}) in model.allowed_joins()
    assert "logged_customer_id" not in model.allowed_columns("supervisor")["interactions"]
    assert "fraud_risk_score" not in model.allowed_columns("customer")["claims"]
    assert "fraud_risk_score" in model.allowed_columns("claims_agent")["claims"]


@pytest.mark.unit
def test_AC_02_01_rule_results_hidden_from_claims_agent_prompt() -> None:
    model = SemanticModel.load()
    assert "rule_results" in model.tables_for("supervisor")
    assert "rule_results" not in model.tables_for("claims_agent")
    assert "gold.rule_results" in model.prompt_context("supervisor")
    agent_prompt = model.prompt_context("claims_agent")
    assert "gold.rule_results" not in agent_prompt and "paid despite blockers" not in agent_prompt
    assert "silver.customer_interactions.claim_id = silver.claims.claim_id" in agent_prompt


def _broken(tmp_path: Path, mutate: object) -> Path:
    raw = yaml.safe_load(SEMANTIC_MODEL_FILE.read_text(encoding="utf-8"))
    mutate(raw)  # type: ignore[operator]
    path = tmp_path / "model.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


@pytest.mark.unit
@pytest.mark.parametrize(
    "mutate",
    [
        lambda m: m["relationships"][0].update(left_table="payments"),
        lambda m: m["relationships"][0]["relationship_columns"][0].update(left_column="nope"),
        lambda m: m["tables"][0].update(primary_key={"columns": ["nope"]}),
        lambda m: m["tables"][0]["dimensions"].append(dict(m["tables"][0]["dimensions"][0])),
        lambda m: m["tables"][0]["dimensions"][0].update(colour="red"),
    ],
    ids=["unknown_table", "unknown_join_column", "bad_primary_key", "duplicate_column", "unknown_key"],
)
def test_AC_02_01_bad_model_rejected(tmp_path: Path, mutate: object) -> None:
    with pytest.raises(ValidationError):
        SemanticModel.load(_broken(tmp_path, mutate))


@pytest.fixture(scope="module")
def warehouse() -> duckdb.DuckDBPyConnection:
    path = get_settings().paths.warehouse
    if not path.exists():
        pytest.skip("data/warehouse.duckdb not built: run `make data`")
    con = duckdb.connect(str(path), read_only=True)
    yield con  # type: ignore[misc]
    con.close()


@pytest.mark.integration
def test_AC_02_01_every_table_and_column_expr_exists_in_duckdb(warehouse: duckdb.DuckDBPyConnection) -> None:
    model = SemanticModel.load()
    for t in model.tables:
        table = t.base_table.qualified
        for c in t.columns:
            warehouse.execute(f"SELECT {c.expr} FROM {table} LIMIT 0")
        for m in t.metrics:
            warehouse.execute(f"SELECT {m.expr} FROM {table}")
        for f in t.filters:
            warehouse.execute(f"SELECT COUNT(*) FROM {table} WHERE {f.expr}")
        for b in t.blocked_columns:
            warehouse.execute(f"SELECT {b} FROM {table} LIMIT 0")  # blocked, but it must exist to block it


# Values the derivation can produce but no row has at the as-of date (spec 01: no policy starts after it).
POSSIBLE_BUT_ABSENT = {("policies", "effective_status"): {"Not Started"}}


@pytest.mark.integration
def test_AC_02_01_sample_values_exist_in_the_data(warehouse: duckdb.DuckDBPyConnection) -> None:
    """Drift check: every listed enum value occurs in its column (the prompt tells the model to use them)."""
    model = SemanticModel.load()
    for t in model.tables:
        for c in t.columns:
            if not c.is_enum or not c.sample_values:
                continue
            present = {
                str(r[0])
                for r in warehouse.execute(
                    f"SELECT DISTINCT {c.expr} FROM {t.base_table.qualified}"
                ).fetchall()
            }
            missing = (
                {str(v) for v in c.sample_values} - present - POSSIBLE_BUT_ABSENT.get((t.name, c.name), set())
            )
            assert not missing, f"{t.name}.{c.name}: {sorted(missing)}"
