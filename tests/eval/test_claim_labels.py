"""Independent claim labels (insurai.eval.claim_labels): the second implementation of the rules."""

from collections import Counter
from typing import Any

import pytest

from insurai import db
from insurai.eval import claim_labels
from insurai.rules import engine
from insurai.settings import get_settings


@pytest.mark.unit
@pytest.mark.parametrize(
    ("claim", "sum_insured", "deductible", "co_pay", "expected"),
    [
        (64577, 500000, 0, 10, 58119),
        (44184, 500000, 10000, 0, 34184),
        (900000, 500000, 0, 0, 500000),
        (5000, 500000, 10000, 10, 0),
    ],
)
def test_expected_payable_deductible_first_then_co_pay(
    claim: int, sum_insured: int, deductible: int, co_pay: int, expected: int
) -> None:
    row = {"claim_amount": claim, "sum_insured": sum_insured, "deductible": deductible, "co_pay_pct": co_pay}
    assert claim_labels.expected_payable(row) == expected


@pytest.mark.integration
@pytest.mark.slow
def test_independent_derivation_matches_the_engine_on_every_claim() -> None:
    """Two implementations, 120,000 claims, 12 rules and 4 flags: zero disagreements."""
    if not get_settings().paths.warehouse.exists():
        pytest.skip("data/warehouse.duckdb not built: run `make data`")
    with db.connect(read_only=True) as con:
        derived = {d.row["claim_id"]: d for d in claim_labels.load(con)}
        ruleset, sql = engine.compiled()
        ids = [r.id for r in ruleset.rules]
        flags = [f.id for f in ruleset.decision_consistency]
        rows = con.execute(f"SELECT claim_id, {', '.join(ids + flags)} FROM ({sql})").fetchall()
    diffs: Counter[str] = Counter()
    for row in rows:
        d: Any = derived[row[0]]
        values = dict(zip(ids + flags, row[1:], strict=True))
        diffs.update(r for r in ids if d.rules[r] != values[r])
        diffs.update(f for f in flags if (f in d.consistency) != bool(values[f]))
    assert len(rows) == 120_000 and not diffs, dict(diffs)
