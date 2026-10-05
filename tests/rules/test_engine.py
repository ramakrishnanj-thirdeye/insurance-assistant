"""Rules engine (spec 07): loading and validation, compilation, single-claim evaluation, portfolio counts."""

import re
import shutil
import statistics
import time
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pytest
from claim_items import all_items, item_ids, seed_items, write_rules

from insurai.rules import engine
from insurai.rules.engine import RulesConfigError, compile_rules, evaluate_claim, load_rules, load_ruleset
from insurai.rules.render import Formats, RenderError, render
from insurai.rules.schemas import ClaimAssessment
from insurai.settings import get_settings

FAILS = {
    "R01": 98_375,
    "R02": 3_589,
    "R03": 16_346,
    "R04": 4_798,
    "R05": 2_753,
    "R06": 107_729,
    "R07": 13_942,
    "R08": 17_992,
    "R09": 35_124,
    "R10": 1_164,
    "R11": 6_000,
    "R12": 28_279,
}
CONSISTENCY = {"C1": 59_627, "C2": 514, "C3": 241, "C4": 1_412}
MATERNITY_PAID_EXCLUDED = 1_390
DEMO_CLAIMS = ("CLM300210", "CLM300500", "CLM300101")
SNAKE = re.compile(r"\b[a-z0-9]+_[a-z0-9_]+\b")

MINIMAL = """
version: 2
citations:
  reimbursement: {{product: ALL, section_no: 8, section_name: "Reimbursement Process"}}
  human_review:  {{product: ALL, section_no: 13, section_name: "Human Review"}}
rules:
  - id: R01
    name: In force
    severity: blocker
    pass_if: "in_policy_period"
    evidence: [claim_date]
    message: "Claim date {{claim_date}} is outside the period."
    cite: schedule
  - id: R99
    name: Bad rule
    severity: blocker
    pass_if: "{expr}"
    evidence: [claim_date]
    message: "{message}"
    cite: none
"""


@pytest.fixture
def facts_con() -> Any:
    """An in-memory gold.claim_facts with the columns the minimal rules need."""
    con = duckdb.connect()
    con.execute("CREATE SCHEMA gold")
    con.execute(
        "CREATE TABLE gold.claim_facts (claim_id VARCHAR, claim_date DATE, in_policy_period BOOLEAN, "
        "fraud_risk_score DOUBLE)"
    )
    yield con
    con.close()


def _rules(tmp_path: Path, expr: str = "TRUE", message: str = "Fine.") -> Path:
    return write_rules(tmp_path / "rules.yaml", MINIMAL.format(expr=expr, message=message))


# --- AC-07-01 --------------------------------------------------------------------------------------------


@pytest.mark.unit
def test_AC_07_01_unknown_column_rejected_with_rule_id(tmp_path: Path, facts_con: Any) -> None:
    with pytest.raises(RulesConfigError, match=r"R99\.pass_if.*no_such_column"):
        load_rules(_rules(tmp_path, expr="no_such_column > 0"), facts_con)


@pytest.mark.unit
def test_AC_07_01_unknown_threshold_and_placeholder_rejected(tmp_path: Path, facts_con: Any) -> None:
    with pytest.raises(RulesConfigError, match=r"R99\.pass_if: unknown threshold 'nope'"):
        load_rules(_rules(tmp_path, expr="fraud_risk_score < {nope}"), facts_con)
    with pytest.raises(RulesConfigError, match=r"R99\.message: unknown placeholder"):
        load_rules(_rules(tmp_path, message="Score {not_a_column}."), facts_con)


@pytest.mark.unit
def test_AC_07_01_valid_rules_load(tmp_path: Path, facts_con: Any) -> None:
    rules = load_rules(_rules(tmp_path, expr="fraud_risk_score < {fraud_review_score}"), facts_con)
    assert [r.id for r in rules] == ["R01", "R99"]


@pytest.mark.unit
def test_compile_rules_status_order_and_null_is_false(facts_con: Any, tmp_path: Path) -> None:
    rules = load_rules(_rules(tmp_path, expr="fraud_risk_score < {fraud_review_score}"), facts_con)
    facts_con.execute(
        "INSERT INTO gold.claim_facts VALUES ('C1', DATE '2025-01-01', TRUE, 0.9), "
        "('C2', DATE '2025-01-01', NULL, NULL), ('C3', DATE '2025-01-01', FALSE, 0.1)"
    )
    sql = compile_rules(rules, {"fraud_review_score": 0.5})
    got = facts_con.execute(f"SELECT claim_id, R01, R99 FROM ({sql}) ORDER BY claim_id").fetchall()
    assert got == [("C1", "pass", "fail"), ("C2", "fail", "fail"), ("C3", "fail", "pass")]


# --- AC-07-05 (unit) -------------------------------------------------------------------------------------


@pytest.mark.unit
def test_AC_07_05_render_inr_grouping_dates_lists_none() -> None:
    fmt = Formats(inr=frozenset({"expected_payable", "sum_insured"}))
    values = {
        "expected_payable": 58119,
        "sum_insured": 500000,
        "claim_date": date(2025, 3, 4),
        "docs": ["Claim Form", "ID Proof"],
        "empty": [],
        "missing": None,
    }
    text = render(
        "{expected_payable} of {sum_insured} on {claim_date}: {docs}; {empty}; {missing}", values, fmt
    )
    assert text == "₹58,119 of ₹5,00,000 on 2025-03-04: Claim Form, ID Proof; none; none"


@pytest.mark.unit
def test_render_rejects_unknown_placeholder_and_stray_brace() -> None:
    with pytest.raises(RenderError):
        render("{nope}", {}, Formats())
    with pytest.raises(RenderError):
        render("text with { brace", {}, Formats())


# --- integration: one claim ------------------------------------------------------------------------------


def _assessment(
    claim_id: str, persona: str = "claims_agent", principal_id: str | None = None
) -> ClaimAssessment:
    result = evaluate_claim(claim_id, persona, principal_id=principal_id)  # type: ignore[arg-type]
    assert isinstance(result, ClaimAssessment), result
    return result


@pytest.mark.integration
@pytest.mark.parametrize("item", seed_items(), ids=item_ids(seed_items()))
def test_AC_07_02_demo_claims_match_seed_labels(warehouse_ready: None, item: dict[str, Any]) -> None:
    labels = item["labels"]
    a = _assessment(labels["claim_id"])
    assert {r.id: r.status for r in a.rules} == labels["expected_rules"]
    assert a.checklist.missing == labels["expected_missing"]
    assert a.checklist.pending == labels["expected_pending"]
    assert a.checklist.untracked == labels.get("expected_untracked", [])
    assert [c.id for c in a.consistency] == labels["expected_consistency"]
    assert a.needs_human_review is labels["needs_human_review"]
    for key, value in labels["facts"].items():
        assert a.facts[key] == value, key


@pytest.mark.integration
@pytest.mark.parametrize("item", all_items(), ids=item_ids(all_items()))
def test_AC_07_02_draft_items_match_independent_labels(warehouse_ready: None, item: dict[str, Any]) -> None:
    """The draft items' labels come from insurai.eval.claim_labels (plain Python over silver.*)."""
    labels = item["labels"]
    a = _assessment(labels["claim_id"])
    assert {r.id: r.status for r in a.rules} == labels["expected_rules"]
    assert (a.checklist.missing, a.checklist.pending) == (
        labels["expected_missing"],
        labels["expected_pending"],
    )
    assert a.checklist.rejected == labels.get("expected_rejected", a.checklist.rejected)
    assert [c.id for c in a.consistency] == labels["expected_consistency"]
    assert a.needs_human_review is labels["needs_human_review"]


@pytest.mark.integration
@pytest.mark.parametrize("claim_id", DEMO_CLAIMS)
def test_AC_07_05_demo_messages_have_no_braces_and_inr_grouping(warehouse_ready: None, claim_id: str) -> None:
    a = _assessment(claim_id)
    texts = [r.message for r in a.rules if r.message] + a.next_best_actions + a.escalation_reasons
    assert texts
    for text in texts:
        assert "{" not in text and "}" not in text, text
        for amount in re.findall(r"₹[\d,]+", text):
            digits = amount[1:].replace(",", "")
            assert amount == "₹" + _indian(int(digits)), text
    if claim_id == "CLM300210":
        r09 = next(r for r in a.rules if r.id == "R09")
        assert "₹58,119" in (r09.message or "") and "₹64,577" in (r09.message or "")


def _indian(n: int) -> str:
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return ",".join([head, *groups, tail]) if head else ",".join([*groups, tail])


@pytest.mark.integration
def test_every_message_variant_in_the_data_reads_as_plain_language(warehouse: Any) -> None:
    """Render every (rule, status, message variant) that occurs in the portfolio: no snake_case."""
    ruleset, sql = engine.compiled()
    seen = 0
    for rule in ruleset.rules:
        msg_col = f"{rule.id}_message" if rule.message_if else "NULL"
        rows = warehouse.execute(
            f"SELECT arg_min(claim_id, claim_id) FROM ({sql}) WHERE {rule.id} IN ('fail', 'review') "
            f"GROUP BY {rule.id}, {msg_col} ORDER BY 1"
        ).fetchall()
        for (claim_id,) in rows:
            a = _assessment(claim_id)
            result = next(r for r in a.rules if r.id == rule.id)
            assert result.message, (rule.id, claim_id)
            assert not SNAKE.search(result.message), result.message
            for action in a.next_best_actions:
                assert not SNAKE.search(action), action
            seen += 1
    assert seen >= len(ruleset.rules)


@pytest.mark.integration
def test_citations_follow_the_cite_kind(warehouse_ready: None) -> None:
    a = _assessment("CLM300210")
    by_id = {r.id: r for r in a.rules}
    assert by_id["R01"].citation and by_id["R01"].citation.label == "[policies:POL218917]"
    assert by_id["R05"].citation and by_id["R05"].citation.label.startswith("[Critical Care Elite §")
    assert by_id["R06"].citation and by_id["R06"].citation.label == "[All products §8 Reimbursement Process]"
    assert by_id["R02"].citation is None  # pass results carry no citation
    labels = {s.label for s in a.sources}
    assert {r.citation.label for r in a.rules if r.citation} <= labels


@pytest.mark.integration
def test_AC_07_06_customer_view_hides_r10_r12_fraud_and_flags(warehouse_ready: None) -> None:
    a = _assessment("CLM300210", "customer", principal_id="CUST139920")
    assert a.view == "customer"
    ids = {r.id for r in a.rules}
    assert "R10" not in ids and "R12" not in ids
    assert "fraud_risk_score" not in a.facts and "manual_review_flag" not in a.facts
    dumped = a.model_dump_json()
    assert "fraud_risk_score" not in dumped and "fraud" not in dumped.lower()
    assert a.consistency == [] and a.escalation_reasons == []
    assert a.next_best_actions and a.next_best_actions[0].startswith("Upload ")
    assert not any("manual review queue" in x for x in a.next_best_actions)


@pytest.mark.integration
def test_customer_cannot_evaluate_another_customers_claim(warehouse_ready: None) -> None:
    result = evaluate_claim("CLM300210", "customer", principal_id="CUST000001")
    assert getattr(result, "kind", None) == "access_denied"
    assert getattr(evaluate_claim("CLM999999", "claims_agent"), "kind", None) == "not_found"


@pytest.mark.integration
def test_AC_07_08_evaluate_claim_under_300ms(warehouse_ready: None) -> None:
    for claim_id in DEMO_CLAIMS:
        _assessment(claim_id)  # warm the ruleset, section names and DuckDB caches
    timings = []
    for _ in range(3):
        for claim_id in DEMO_CLAIMS:
            start = time.perf_counter()
            _assessment(claim_id)
            timings.append((time.perf_counter() - start) * 1000)
    assert statistics.median(timings) < 300, timings


# --- integration: portfolio ------------------------------------------------------------------------------


def _counts(con: Any, thresholds: dict[str, float] | None = None) -> dict[str, int]:
    ruleset = load_ruleset(engine.RULES_FILE, con)
    sql = compile_rules(
        ruleset.rules,
        thresholds or engine._thresholds(),
        consistency=ruleset.decision_consistency,
        insights=ruleset.insights,
    )
    ids = [r.id for r in ruleset.rules]
    flags = [f.id for f in [*ruleset.decision_consistency, *ruleset.insights]]
    select = ", ".join(
        [f"count(*) FILTER (WHERE {r} = 'fail') AS {r}" for r in ids]
        + [f"count(*) FILTER (WHERE {f}) AS {f}" for f in flags]
    )
    cur = con.execute(f"SELECT {select} FROM ({sql})")
    return dict(zip([d[0] for d in cur.description], cur.fetchone(), strict=True))


@pytest.mark.integration
def test_AC_07_03_portfolio_fail_counts(warehouse: Any) -> None:
    counts = _counts(warehouse)
    assert {r: counts[r] for r in FAILS} == FAILS


@pytest.mark.integration
def test_AC_07_04_consistency_and_maternity_counts(warehouse: Any) -> None:
    counts = _counts(warehouse)
    assert {c: counts[c] for c in CONSISTENCY} == CONSISTENCY
    assert counts["P1"] == MATERNITY_PAID_EXCLUDED


@pytest.mark.integration
def test_AC_07_09_threshold_change_moves_r10_count(warehouse: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _counts(warehouse)["R10"] == FAILS["R10"]
    monkeypatch.setenv("INSURAI__THRESHOLDS__FRAUD_REVIEW_SCORE", "0.3")
    get_settings.cache_clear()
    lowered = _counts(warehouse)["R10"]
    assert lowered > FAILS["R10"]
    _, sql = engine.compiled()  # the cached single-claim SQL follows the setting too
    assert "0.3" in sql and "0.5)" not in sql


@pytest.mark.integration
def test_AC_07_08_materialise_under_30s(
    warehouse_ready: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`make rules` on a copy of the warehouse: gold.rule_results, the counts, and the time limit."""
    copy = tmp_path / "warehouse.duckdb"
    shutil.copy(get_settings().paths.warehouse, copy)
    monkeypatch.setenv("INSURAI__PATHS__WAREHOUSE", str(copy))
    get_settings.cache_clear()
    from insurai.rules import materialise

    start = time.perf_counter()
    assert materialise.main() == 0
    assert time.perf_counter() - start < 30
    with duckdb.connect(str(copy), read_only=True) as con:
        report = engine.portfolio_counts(con, engine.read_ruleset())
        cols = {r[0] for r in con.execute("DESCRIBE gold.rule_results").fetchall()}
    assert report.claims == 120_000
    assert report.fail_counts == FAILS and report.consistency_counts == CONSISTENCY
    assert report.insight_counts == {"P1": MATERNITY_PAID_EXCLUDED}
    assert {"claim_id", "product_name", "claim_status", "R01", "R04_severity", "C1", "P1"} <= cols
    assert sum(p["R01"] for p in report.by_product.values()) == FAILS["R01"]
