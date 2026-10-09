"""AC-05-02: the sql_facts slice is answered 100% correctly by the tools alone (exact match)."""

from collections import Counter
from collections.abc import Iterator
from datetime import date

import duckdb
import pytest

from insurai import db
from insurai.eval import sql_facts
from insurai.settings import get_settings

AS_OF = date(2026, 10, 1)


@pytest.fixture(scope="module")
def con() -> Iterator[duckdb.DuckDBPyConnection]:
    if not get_settings().paths.warehouse.exists():
        pytest.skip("data/warehouse.duckdb not built: run `make data`")
    with db.connect(read_only=True) as con:
        yield con


@pytest.mark.integration
def test_AC_05_02_sql_facts_tools_exact_match(con: duckdb.DuckDBPyConnection) -> None:
    result = sql_facts.score(sql_facts.load_dataset(), con, AS_OF)
    assert result["metrics"]["items"] == 20
    assert result["metrics"]["tool_errors"] == 0
    assert result["metrics"]["accuracy"] == 1.0, [r for r in result["items"] if not r["correct"]]


@pytest.mark.integration
def test_AC_05_02_generator_deterministic_seed42(con: duckdb.DuckDBPyConnection) -> None:
    first = sql_facts.generate(con)
    assert first == sql_facts.generate(con)
    assert first == sql_facts.load_dataset()  # the committed file is what seed 42 produces


@pytest.mark.integration
def test_AC_05_02_includes_motor_claim_and_zero_missing_docs(con: duckdb.DuckDBPyConnection) -> None:
    items = sql_facts.load_dataset()
    assert Counter(i.tags[0] for i in items) == {
        t.name: sum(n for _, n in t.pools) for t in sql_facts.TEMPLATES
    }
    golds = {i.id: con.execute(i.gold_sql, i.gold_params).fetchone()[0] for i in items}  # type: ignore[index]
    hospital = [i for i in items if i.tags[0] == "hospital_network_status"]
    motor = [
        i
        for i in hospital
        if con.execute("SELECT policy_type FROM silver.claims WHERE claim_id = ?", i.gold_params).fetchone()[
            0
        ]
        == "Motor"
    ]  # type: ignore[index]
    assert motor and all(golds[i.id] is None for i in motor)
    missing = [i for i in items if i.tags[0] == "missing_documents"]
    assert any(golds[i.id] == [] for i in missing)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("a", "b", "equal"),
    [
        (" Approved ", "approved", True),
        (64577, 64577.0, True),
        (["ID Proof", "Claim Form"], ["Claim Form", "ID Proof"], True),
        ([], [], True),
        (None, None, True),
        (None, "Network", False),
        ("Approved", "Partially Approved", False),
        (2, 3, False),
    ],
)
def test_AC_05_02_normalised_exact_match(a: object, b: object, equal: bool) -> None:
    assert (sql_facts.normalise(a) == sql_facts.normalise(b)) is equal


@pytest.mark.unit
def test_AC_05_02_resolve_dotted_path() -> None:
    assert (
        sql_facts.resolve({"hospital": {"network_status": "Network"}}, "hospital.network_status") == "Network"
    )
    assert sql_facts.resolve({"hospital": None}, "hospital.network_status") is None


@pytest.mark.unit
def test_AC_05_02_eval_gate_fails_below_target() -> None:
    from insurai.eval.run import gate

    results = {"sql_facts": {"metrics": {"accuracy": 0.95}}}
    targets = {"sql_facts.accuracy": 1.0, "policy_clauses.recall_at_5": 0.95}
    assert gate(results, None, targets) == [
        "sql_facts.accuracy = 0.95 misses target min 1.0 (no baseline value)"
    ]
    assert gate({"sql_facts": {"metrics": {"accuracy": 1.0}}}, None, targets) == []
