"""Throwaway reference prototype: proves the configs + reference SQL work end to end.

Builds ref tables from YAML, runs specs/reference/warehouse.sql, compiles config/rules.yaml to SQL,
and evaluates it for one claim and for the whole portfolio. Claude Code should reimplement this
properly per specs 01, 03 and 07 (typed models, tests, settings loader), not import it.

Usage:  python specs/reference/prototype_build_and_rules.py [raw_dir] [claim_id ...]
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import duckdb
import yaml

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "config"


def load_yaml(name: str) -> dict:
    return yaml.safe_load((CFG / name).read_text(encoding="utf-8"))


def months_to_days(m: float | None) -> int:
    return int(round(m * 365 / 12)) if m else 0


def build_ref_tables(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("CREATE SCHEMA IF NOT EXISTS ref")
    # required documents -> one row per (policy_type, document_type, optional condition)
    rd = load_yaml("required_documents.yaml")
    rows = []
    for ptype, spec in rd["policy_types"].items():
        for doc in spec["always"]:
            rows.append((ptype, doc, None, None))
        for cond in spec.get("conditional", []):
            w = cond["when"]
            vals = w.get("in") or [w["equals"]]
            for doc in cond["add"]:
                rows.append((ptype, doc, w["field"], vals))
    con.execute("CREATE OR REPLACE TABLE ref.required_documents(policy_type VARCHAR, document_type VARCHAR, "
                "condition_field VARCHAR, condition_values VARCHAR[])")
    con.executemany("INSERT INTO ref.required_documents VALUES (?, ?, ?, ?)", rows)

    # coverage grid: every product x every diagnosis of its policy type
    cm = load_yaml("coverage_matrix.yaml")
    dc = cm["diagnosis_coverage"]
    exempt = set(dc["assumptions"]["A1_accident_exempt"]["diagnoses"])
    specified = set(dc["assumptions"]["A2_specified_diseases"]["diagnoses"])
    grid = []
    for product, p in cm["products"].items():
        w = p.get("waiting") or {}
        for diag in dc["diagnoses"][p["policy_type"]]:
            status, section, basis, reason = dc["default_status"], None, "document", None
            waits: list[tuple[int, str, str]] = []  # (days, basis, label)
            if w.get("initial_days"):
                waits.append((w["initial_days"], "document", f"initial {w['initial_days']} days §4"))
            if w.get("specified_disease_months") and diag in specified:
                d = months_to_days(w["specified_disease_months"])
                waits.append((d, "assumption", f"specified disease {w['specified_disease_months']} months §4"))
            for ov in [o for o in dc["overrides"] if o["product"] == product and o["diagnosis"] in ("*", diag)]:
                # specific diagnosis overrides beat "*" because they are listed after it
                status, section, basis = ov["status"], ov.get("section"), ov.get("basis", "document")
                reason = ov.get("reason", reason)
                cw = ov.get("condition_waiting_days") or months_to_days(ov.get("condition_waiting_months"))
                if cw:
                    waits.append((cw, ov.get("basis", "document"), f"condition waiting {cw} days §{ov.get('section')}"))
            if diag in exempt:
                waits = []
            req, wbasis, wreason = 0, None, None
            if waits:
                req, wbasis, wreason = max(waits, key=lambda t: t[0])
            grid.append((product, diag, status, req, wbasis, wreason, section, basis, reason))
    con.execute("CREATE OR REPLACE TABLE ref.diagnosis_coverage(product_name VARCHAR, diagnosis VARCHAR, "
                "coverage_status VARCHAR, required_waiting_days INTEGER, waiting_basis VARCHAR, waiting_reason VARCHAR, "
                "section_no INTEGER, coverage_basis VARCHAR, reason VARCHAR)")
    con.executemany("INSERT INTO ref.diagnosis_coverage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", grid)


def compile_rules(settings: dict) -> tuple[str, list[dict]]:
    rules = load_yaml("rules.yaml")["rules"]
    params = settings["thresholds"]
    cols = []
    for r in rules:
        def sub(expr: str) -> str:
            return re.sub(r"\{(\w+)\}", lambda m: str(params[m.group(1)]), expr)
        applies = sub(r.get("applies_if", "TRUE"))
        passes = sub(r["pass_if"])
        review = sub(r.get("review_if", "FALSE"))
        cols.append(
            f"CASE WHEN NOT coalesce(({applies}), FALSE) THEN 'not_applicable' "
            f"WHEN coalesce(({passes}), FALSE) THEN 'pass' "
            f"WHEN coalesce(({review}), FALSE) THEN 'review' ELSE 'fail' END AS {r['id']}"
        )
    return "SELECT claim_id, claim_status, " + ", ".join(cols) + " FROM gold.claim_facts", rules


def main() -> None:
    raw_dir = sys.argv[1] if len(sys.argv) > 1 else "data/raw"
    claim_ids = sys.argv[2:] or ["CLM300210", "CLM300500", "CLM300101"]
    settings = load_yaml("settings.yaml")
    con = duckdb.connect()
    con.execute(f"SET VARIABLE as_of = DATE '{settings['as_of_date']}'")
    con.execute(f"SET VARIABLE high_value = {settings['thresholds']['high_value_inr']}")
    con.execute(f"SET VARIABLE raw_dir = '{raw_dir}'")
    t = time.time()
    build_ref_tables(con)
    con.execute((ROOT / "specs/reference/warehouse.sql").read_text(encoding="utf-8"))
    print(f"warehouse built in {time.time() - t:.1f}s")
    sql, rules = compile_rules(settings)
    con.execute(f"CREATE OR REPLACE TABLE gold.rule_results AS {sql}")
    for cid in claim_ids:
        print(con.execute("SELECT * FROM gold.rule_results WHERE claim_id = ?", [cid]).df().T.to_string())
    print(con.execute("SELECT " + ", ".join(
        f"count(*) FILTER (WHERE {r['id']} = 'fail') AS {r['id']}_fail" for r in rules) + " FROM gold.rule_results").df().T)


if __name__ == "__main__":
    main()
