"""sql_facts slice (spec 11): seeded generator over 8 fact templates and a tools-only exact-match scorer.

Items store the question and the parameterised SQL that answers it; the gold value is recomputed from the
warehouse on every run, never stored. 20 items (3-day scope; spec 11 says 40).

    python -m insurai.eval.sql_facts --write    # regenerate eval/datasets/sql_facts.jsonl
    python -m insurai.eval.sql_facts            # score the committed file
"""

import argparse
import json
import random
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
from pydantic import BaseModel

from insurai import db
from insurai.observability import get_logger
from insurai.settings import ROOT, get_settings
from insurai.tools.registry import TOOLS
from insurai.tools.schemas import AccessDenied, NotFound, Persona, ToolContext

log = get_logger(__name__)

SLICE = "sql_facts"
DATASET = ROOT / "eval" / "datasets" / "sql_facts.jsonl"
SEED = 42
OPEN_STATUSES = "('Submitted', 'Under Review', 'Pending Documents')"


@dataclass(frozen=True)
class Template:
    name: str
    question: str  # formatted with {key}
    pools: tuple[tuple[str, int], ...]  # (SQL returning candidate keys, how many to sample)
    gold_sql: str  # one parameter: the key
    tool: str
    arg: str
    answer_path: str  # dotted path into the tool result
    route: tuple[str, ...]
    source_table: str


TEMPLATES: tuple[Template, ...] = (
    Template(
        "claim_status",
        "What is the status of claim {key}?",
        (("SELECT claim_id FROM silver.claims", 3),),
        "SELECT claim_status FROM silver.claims WHERE claim_id = ?",
        "get_claim",
        "claim_id",
        "claim_status",
        ("claim_status",),
        "claims",
    ),
    Template(
        "approved_amount",
        "How much was approved on claim {key}?",
        (("SELECT claim_id FROM silver.claims WHERE claim_status IN ('Approved', 'Partially Approved')", 3),),
        "SELECT approved_amount FROM silver.claims WHERE claim_id = ?",
        "get_claim",
        "claim_id",
        "approved_amount",
        ("claim_status",),
        "claims",
    ),
    Template(
        "missing_documents",
        "Which required documents are still missing for claim {key}?",
        (
            ("SELECT claim_id FROM gold.claim_facts WHERE docs_required_missing > 0", 2),
            ("SELECT claim_id FROM gold.claim_facts WHERE docs_required_missing = 0", 1),  # nothing missing
        ),
        """SELECT coalesce(list(document_type ORDER BY document_type), [])
           FROM gold.claim_doc_checklist
           WHERE claim_id = ? AND required AND checklist_status IN ('No record', 'Missing')""",
        "get_claim_documents",
        "claim_id",
        "missing",
        ("claim_documents",),
        "claim_documents",
    ),
    Template(
        "hospital_network_status",
        "Is the hospital on claim {key} in our network?",
        (
            ("SELECT claim_id FROM silver.claims WHERE policy_type = 'Health'", 2),
            (
                "SELECT claim_id FROM silver.claims WHERE policy_type = 'Motor'",
                1,
            ),  # no hospital: gold is null
        ),
        """SELECT h.network_status FROM silver.claims c
           LEFT JOIN silver.hospitals h ON h.hospital_id = c.hospital_id WHERE c.claim_id = ?""",
        "get_claim",
        "claim_id",
        "hospital.network_status",
        ("hospital_check",),
        "claims",
    ),
    Template(
        "policy_effective_status",
        "Is policy {key} in force?",
        (("SELECT policy_id FROM silver.policies", 2),),
        "SELECT effective_status FROM silver.policies WHERE policy_id = ?",
        "get_policy",
        "policy_id",
        "effective_status",
        ("policy_details",),
        "policies",
    ),
    Template(
        "policy_sum_insured",
        "What is the sum insured on policy {key}?",
        (("SELECT policy_id FROM silver.policies", 2),),
        "SELECT sum_insured FROM silver.policies WHERE policy_id = ?",
        "get_policy",
        "policy_id",
        "sum_insured",
        ("policy_details",),
        "policies",
    ),
    Template(
        "customer_open_claims",
        "How many open claims does customer {key} have?",
        (("SELECT DISTINCT customer_id FROM silver.claims", 2),),
        f"SELECT count(*) FROM silver.claims WHERE customer_id = ? AND claim_status IN {OPEN_STATUSES}",
        "get_customer_summary",
        "customer_id",
        "claims_open",
        ("customer_summary",),
        "customers",
    ),
    Template(
        "latest_interaction_intent",
        "What was the customer's latest interaction about on claim {key}?",
        (("SELECT DISTINCT claim_id FROM silver.customer_interactions", 2),),
        """SELECT intent FROM silver.customer_interactions WHERE claim_id = ?
           ORDER BY interaction_date DESC, interaction_id DESC LIMIT 1""",
        "get_claim_interactions",
        "claim_id",
        "latest_intent",
        ("claim_interactions",),
        "interactions",
    ),
)


class SqlFactItem(BaseModel):
    """The eval/README item schema plus the fields this slice scores with."""

    id: str
    slice: str = SLICE
    persona: Persona = "claims_agent"
    principal_id: str | None = None
    turns: list[dict[str, str]]
    expected_route: list[str]
    expected_entities: dict[str, str]
    gold_answer: Any = None  # recomputed from gold_sql on every run
    gold_sources: list[str]
    gold_sql: str
    gold_params: list[str]
    must_refuse: bool = False
    refusal_code: str | None = None
    tags: list[str]
    tool: str
    tool_args: dict[str, str]
    answer_path: str


def generate(con: duckdb.DuckDBPyConnection, seed: int = SEED) -> list[SqlFactItem]:
    rng = random.Random(seed)
    items: list[SqlFactItem] = []
    for t in TEMPLATES:
        for pool_sql, n in t.pools:
            keys = sorted(str(r[0]) for r in con.execute(pool_sql).fetchall())
            for key in rng.sample(keys, n):
                items.append(
                    SqlFactItem(
                        id=f"SQL{len(items) + 1:03d}",
                        turns=[{"role": "user", "content": t.question.format(key=key)}],
                        expected_route=list(t.route),
                        expected_entities={t.arg: key},
                        gold_sources=[f"{t.source_table}:{key}"],
                        gold_sql=" ".join(t.gold_sql.split()),
                        gold_params=[key],
                        tags=[t.name],
                        tool=t.tool,
                        tool_args={t.arg: key},
                        answer_path=t.answer_path,
                    )
                )
    return items


def write_dataset(items: list[SqlFactItem], path: Path = DATASET) -> None:
    lines = [json.dumps(i.model_dump(), ensure_ascii=False) for i in items]
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))


def load_dataset(path: Path = DATASET) -> list[SqlFactItem]:
    text = path.read_text(encoding="utf-8")
    return [SqlFactItem.model_validate_json(line) for line in text.splitlines() if line.strip()]


def score(items: list[SqlFactItem], con: duckdb.DuckDBPyConnection, as_of: date) -> dict[str, Any]:
    """Call each item's tool in-process and compare the answer with the recomputed gold value."""
    rows: list[dict[str, Any]] = []
    for item in items:
        row = con.execute(item.gold_sql, item.gold_params).fetchone()
        gold = row[0] if row else None
        ctx = ToolContext(
            persona=item.persona, principal_id=item.principal_id, as_of=as_of, trace_id=f"eval-{item.id}"
        )
        result = TOOLS[item.tool](ctx, **item.tool_args)
        error = isinstance(result, (NotFound, AccessDenied))
        answer = None if error else resolve(result.model_dump(mode="json"), item.answer_path)
        rows.append(
            {
                "id": item.id,
                "template": item.tags[0],
                "gold": _jsonable(gold),
                "answer": answer,
                "correct": not error and normalise(answer) == normalise(gold),
                "tool_error": getattr(result, "kind", None) if error else None,
            }
        )
    n = len(rows)
    metrics = {
        "items": n,
        "accuracy": round(sum(r["correct"] for r in rows) / n, 4) if n else 0.0,
        "tool_errors": sum(r["tool_error"] is not None for r in rows),
        "wrong": [r["id"] for r in rows if not r["correct"]],
    }
    return {"metrics": metrics, "items": rows}


def resolve(data: Any, path: str) -> Any:
    for part in path.split("."):
        if not isinstance(data, dict):
            return None
        data = data.get(part)
    return data


def normalise(value: Any) -> Any:
    """Exact match after trimming and case-folding strings, numbers as numbers, lists as sorted sets."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    if isinstance(value, str):
        return " ".join(value.split()).casefold()
    if isinstance(value, (list, tuple)):
        return tuple(sorted({normalise(v) for v in value}, key=repr))
    return str(value)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def run_slice() -> dict[str, Any]:
    with db.connect(read_only=True) as con:
        return score(load_dataset(), con, get_settings().as_of_date)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="insurai.eval.sql_facts")
    parser.add_argument("--write", action="store_true", help="regenerate the dataset (seed 42)")
    args = parser.parse_args(argv)
    if args.write:
        with db.connect(read_only=True) as con:
            items = generate(con)
        write_dataset(items)
        log.info("wrote %d items to %s", len(items), DATASET)
        return 0
    result = run_slice()
    log.info("sql_facts: %s", result["metrics"])
    return 0 if result["metrics"]["accuracy"] == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
