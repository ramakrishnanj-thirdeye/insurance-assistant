"""analytics slice (spec 11, spec 02 AC-02-07): dataset shape, gold SQL and the exec_accuracy scorer."""

import json
from typing import Any

import pytest
import sqlglot
from sqlglot import exp

from insurai import db
from insurai.eval.analytics import (
    DATASET,
    gold_rows,
    load_items,
    load_probes,
    ordered,
    same_result,
    unsafe_blocked,
)
from insurai.semantic.model import load_semantic_model
from insurai.semantic.schemas import ValidatedSql
from insurai.semantic.sql import validate
from insurai.settings import get_settings

ITEMS = load_items()


@pytest.mark.unit
def test_AC_02_07_dataset_has_15_valid_items() -> None:
    """15 items (decided 2026-10-08, 3-day scope; spec 11 says 20): 12 general, 3 supervisor rule_results."""
    raw = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(ITEMS) == len(raw) == 15
    assert [i.id for i in ITEMS] == [f"ANA{n:03d}" for n in range(1, 16)]
    assert all(r["slice"] == "analytics" and r["expected_route"] == ["analytics"] for r in raw)
    assert all(not r["must_refuse"] and r["gold_sql"] for r in raw)
    assert all(i.persona in ("claims_agent", "supervisor") for i in ITEMS)
    assert sum("rule_results" in i.tags for i in ITEMS) == 3
    assert all(i.persona == "supervisor" for i in ITEMS if "rule_results" in i.tags)
    assert sum("names" in i.tags and i.persona == "claims_agent" for i in ITEMS) == 2


@pytest.mark.unit
def test_AC_02_07_items_stay_draft_until_signed_off() -> None:
    """Every item has a checklist section; an item whose box is unticked keeps its `draft` tag."""
    checklist = (DATASET.parent / "analytics_checklist.md").read_text(encoding="utf-8")
    sections = {s.split(" ", 1)[0]: s for s in checklist.split("\n## ")[1:]}
    assert set(sections) == {i.id for i in ITEMS}
    for item in ITEMS:
        if "- [ ] signed off" in sections[item.id]:
            assert "draft" in item.tags, item.id


@pytest.mark.unit
def test_AC_02_07_gold_sql_passes_the_validator_for_its_persona() -> None:
    model = load_semantic_model()
    for item in ITEMS:
        assert isinstance(validate(item.gold_sql, item.persona, model), ValidatedSql), item.id


@pytest.mark.integration
def test_AC_02_07_gold_sql_runs_and_returns_rows() -> None:
    if not get_settings().paths.warehouse.exists():
        pytest.skip("data/warehouse.duckdb not built: run `make data`")
    for item in ITEMS:
        assert gold_rows(item), item.id


@pytest.mark.unit
def test_AC_02_07_unsafe_probes_all_blocked() -> None:
    assert unsafe_blocked(load_probes()) == (1.0, [])


@pytest.mark.unit
@pytest.mark.parametrize(
    ("got", "gold", "keep_order", "same"),
    [
        ([["Health", 10], ["Motor", 5]], [["Motor", 5], ["Health", 10]], False, True),  # row order ignored
        ([["Health", 10], ["Motor", 5]], [["Motor", 5], ["Health", 10]], True, False),  # ... unless top-N
        ([[10, "Health"]], [["Health", 10]], False, True),  # column order and names ignored
        ([[49.8123]], [[49.81]], False, True),  # floats rounded to 2 dp
        ([[49.8]], [[49.81]], False, False),
        ([[3]], [[3.0]], False, True),
        ([["Health", 10, 1]], [["Health", 10]], False, False),  # extra column
        ([["Health", 10]], [["Health", 10], ["Motor", 5]], False, False),  # missing row
        ([[None, 1]], [[None, 1]], False, True),
        ([[True]], [[1]], False, False),
    ],
)
def test_AC_02_07_exec_accuracy_scorer(got: list, gold: list, keep_order: bool, same: bool) -> None:  # noqa: ANN001
    assert same_result(got, gold, keep_order) is same


@pytest.mark.unit
def test_AC_02_07_order_counts_only_for_order_by_with_limit() -> None:
    assert ordered("SELECT a FROM t ORDER BY a DESC LIMIT 5")
    assert not ordered("SELECT a FROM t ORDER BY a DESC")
    assert not ordered("SELECT a FROM t LIMIT 5")


def _tie_at_limit(sql: str) -> tuple[Any, Any] | None:
    """For `ORDER BY … LIMIT n`, the ORDER BY key values at positions n and n + 1 when they are equal (the
    top-n rows are then not determined by the query); None when there is no such tie."""
    root = sqlglot.parse_one(sql, dialect="duckdb")
    order, limit = root.args.get("order"), root.args.get("limit")
    if order is None or not isinstance(limit, exp.Limit):
        return None
    n = int(limit.expression.this)
    probe = root.copy()
    for i, o in enumerate(order.expressions):
        key = o.this
        if isinstance(key, exp.Literal) and key.is_int:  # ORDER BY 2: the second projection
            key = root.expressions[int(key.this) - 1].unalias()
        probe.select(exp.alias_(key.copy(), f"_tie_key_{i}"), copy=False)
    probe.limit(n + 1, copy=False)
    with db.connect(read_only=True) as con:
        rows = con.execute(probe.sql(dialect="duckdb")).fetchall()
    width = len(order.expressions)
    if len(rows) <= n or rows[n - 1][-width:] != rows[n][-width:]:
        return None
    return rows[n - 1][-width:], rows[n][-width:]


@pytest.mark.integration
def test_AC_02_07_top_n_gold_queries_have_no_tie_at_the_limit() -> None:
    if not get_settings().paths.warehouse.exists():
        pytest.skip("data/warehouse.duckdb not built: run `make data`")
    ties = {i.id: tie for i in ITEMS if (tie := _tie_at_limit(i.gold_sql))}
    assert not ties


@pytest.mark.integration
def test_tie_detector_finds_the_fifth_place_tie() -> None:
    """Fifth and sixth biggest claims both claimed 1,400,000 (why ANA011 asks for four)."""
    if not get_settings().paths.warehouse.exists():
        pytest.skip("data/warehouse.duckdb not built: run `make data`")
    biggest = "SELECT claim_id, claim_amount FROM silver.claims ORDER BY claim_amount DESC LIMIT {n}"
    assert _tie_at_limit(biggest.format(n=5)) == ((1400000,), (1400000,))
    assert _tie_at_limit(biggest.format(n=4)) is None
    assert _tie_at_limit("SELECT claim_id, claim_amount FROM silver.claims ORDER BY 2 DESC LIMIT 5")
