"""analytics slice (spec 11, spec 02 AC-02-07): run_analytics against hand-written gold SQL.

exec_accuracy (spec 11): result sets equal after sorting rows, rounding floats to 2 dp, ignoring column
names; row order is compared only when the gold SQL has ORDER BY with LIMIT. Column order is ignored too
(each row is compared as a sorted tuple of values), but the number of columns must match. Gold SQL runs
through the same validator and executor as the item's persona, so masked names compare as initials.

unsafe_blocked: share of eval/probes/unsafe_sql.yaml rejected with the expected reason (target 1.0).

    python -m insurai.eval.run --suite fast --slice analytics
"""

import json
import time
from pathlib import Path
from typing import Any

import sqlglot
import yaml
from pydantic import BaseModel, ConfigDict
from sqlglot import exp

from insurai.observability import get_logger
from insurai.semantic.model import load_semantic_model
from insurai.semantic.schemas import QueryResult, SqlRejection
from insurai.semantic.sql import DIALECT, execute, validate
from insurai.settings import ROOT, get_settings
from insurai.tools.analytics import AnalyticsResult
from insurai.tools.registry import TOOLS
from insurai.tools.schemas import Persona, ToolContext

log = get_logger(__name__)

SLICE = "analytics"
DATASET = ROOT / "eval" / "datasets" / "analytics.jsonl"
PROBES = ROOT / "eval" / "probes" / "unsafe_sql.yaml"


class AnalyticsItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    persona: Persona
    turns: list[dict[str, str]]
    gold_sql: str
    tags: list[str] = []

    @property
    def question(self) -> str:
        return self.turns[0]["content"]


class Probe(BaseModel):
    id: str
    reason: str
    sql: str
    persona: Persona = "supervisor"


def load_items(path: Path = DATASET) -> list[AnalyticsItem]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [AnalyticsItem.model_validate_json(line) for line in lines if line.strip()]


def load_probes(path: Path = PROBES) -> list[Probe]:
    return [Probe.model_validate(p) for p in yaml.safe_load(path.read_text(encoding="utf-8"))["probes"]]


# --- scoring --------------------------------------------------------------------------------------------


def ordered(gold_sql: str) -> bool:
    """Row order counts only when the gold SQL has ORDER BY with LIMIT (top-N questions)."""
    root = sqlglot.parse_one(gold_sql, dialect=DIALECT)
    return bool(root.args.get("order")) and isinstance(root.args.get("limit"), exp.Limit)


def _value(x: Any) -> Any:
    if isinstance(x, bool) or x is None:
        return x
    if isinstance(x, int | float):
        return round(float(x), 2)
    return str(x)


def _row(row: list[Any]) -> tuple[str, ...]:
    return tuple(sorted(json.dumps(_value(x)) for x in row))


def same_result(got: list[list[Any]], gold: list[list[Any]], keep_order: bool) -> bool:
    if len(got) != len(gold) or any(len(a) != len(b) for a, b in zip(got, gold, strict=False)):
        return False
    a, b = [_row(r) for r in got], [_row(r) for r in gold]
    return a == b if keep_order else sorted(a) == sorted(b)


def gold_rows(item: AnalyticsItem) -> list[list[Any]]:
    checked = validate(item.gold_sql, item.persona, load_semantic_model())
    if isinstance(checked, SqlRejection):
        raise ValueError(f"{item.id}: gold SQL rejected: {checked}")
    result = execute(checked, get_settings().sql.timeout_s * 3)
    if not isinstance(result, QueryResult):
        raise ValueError(f"{item.id}: gold SQL failed: {result}")
    return result.rows


def unsafe_blocked(probes: list[Probe]) -> tuple[float, list[str]]:
    model = load_semantic_model()
    leaked = []
    for p in probes:
        outcome = validate(p.sql, p.persona, model)
        if not (isinstance(outcome, SqlRejection) and outcome.reason == p.reason):
            leaked.append(p.id)
    return round(1 - len(leaked) / len(probes), 4) if probes else 1.0, leaked


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered_values = sorted(values)
    return round(ordered_values[min(len(values) - 1, int(q * len(values)))], 1)


# --- run ------------------------------------------------------------------------------------------------


def run_item(item: AnalyticsItem) -> dict[str, Any]:
    ctx = ToolContext(persona=item.persona, as_of=get_settings().as_of_date, trace_id=f"eval-{item.id}")
    start = time.perf_counter()
    result = TOOLS["run_analytics"](ctx, item.question)
    latency = (time.perf_counter() - start) * 1000
    gold = gold_rows(item)
    ok = isinstance(result, AnalyticsResult) and same_result(result.rows, gold, ordered(item.gold_sql))
    out = {
        "id": item.id,
        "persona": item.persona,
        "exec_ok": ok,
        "kind": getattr(result, "kind", "?"),
        "attempts": getattr(result, "attempts", 0),
        "sql": getattr(result, "sql", None),
        "reason": getattr(result, "reason", None),
        "rows": getattr(result, "row_count", None),
        "gold_rows": len(gold),
        "latency_ms": round(latency, 1),
    }
    log.info("analytics %s exec_ok=%s kind=%s attempts=%s", item.id, ok, out["kind"], out["attempts"])
    return out


def run_slice() -> dict[str, Any]:
    items = load_items()
    results = [run_item(item) for item in items]
    blocked, leaked = unsafe_blocked(load_probes())
    n = len(results) or 1
    latencies = [r["latency_ms"] for r in results]
    metrics = {
        "items": len(results),
        "exec_accuracy": round(sum(r["exec_ok"] for r in results) / n, 4),
        "unsafe_blocked": blocked,
        "repair_rate": round(sum(r["attempts"] == 2 for r in results) / n, 4),
        "rejected_rate": round(sum(r["kind"] == "analytics_rejected" for r in results) / n, 4),
        "latency_p50_ms": _percentile(latencies, 0.5),
        "latency_p95_ms": _percentile(latencies, 0.95),
        "wrong": [r["id"] for r in results if not r["exec_ok"]],
        "leaked_probes": leaked,
    }
    return {"metrics": metrics, "items": results}
