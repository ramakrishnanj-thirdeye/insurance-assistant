"""Counts `[k, n]` for the proportions of slices that report only ratios (spec 11 reports).

Slices built in M7b (policy_clauses_e2e, comparisons, adversarial, claim_analysis) return `counts`
themselves; for the earlier slices the counts are derived here from their per-item rows, so the slice
modules and the gate keep their shapes. A slice's own `counts` win over derived ones.
"""

from collections.abc import Callable
from typing import Any

Row = dict[str, Any]
# metric -> (row filter, row outcome); a row the filter rejects is not counted
Rule = tuple[Callable[[Row], bool], Callable[[Row], bool]]


def _all(row: Row) -> bool:
    return True


def _key(name: str) -> Callable[[Row], bool]:
    return lambda r: bool(r.get(name))


def _has(name: str) -> Callable[[Row], bool]:
    return lambda r: name in r


ROW_RULES: dict[str, dict[str, Rule]] = {
    "policy_clauses": {"recall_at_5": (_has("recall_at_5"), lambda r: r["recall_at_5"] == 1.0)},
    "sql_facts": {"accuracy": (_all, _key("correct"))},
    "routing": {"intent_accuracy": (_all, _key("intent_ok")), "entity_exact": (_all, _key("entity_ok"))},
    "e2e_sql_facts": {"gold_in_answer": (lambda r: r.get("hit") is not None, _key("hit"))},
    "analytics": {"exec_accuracy": (_all, _key("exec_ok"))},
    "guardrails": {
        "not_refused": (lambda r: not r.get("must_refuse") and "refused" in r, lambda r: not r["refused"]),
        "s15_cited": (_has("s15_cited"), _key("s15_cited")),
        "mandated_wording": (_has("mandated_wording"), _key("mandated_wording")),
        "conflict_rendered": (_has("conflict_rendered"), _key("conflict_rendered")),
    },
}


def derive_counts(slice_name: str, result: dict[str, Any]) -> dict[str, list[int]]:
    """`[k, n]` per proportion of one slice result: derived from its rows, then the slice's own counts."""
    rows: list[Row] = [r for r in result.get("items", []) if isinstance(r, dict)]
    out: dict[str, list[int]] = {}
    for metric, (keep, ok) in ROW_RULES.get(slice_name, {}).items():
        kept = [r for r in rows if keep(r)]
        out[metric] = [sum(ok(r) for r in kept), len(kept)]
    metrics = result.get("metrics", {})
    if slice_name == "analytics" and "unsafe_probes" in metrics:
        probes = int(metrics["unsafe_probes"])
        out["unsafe_blocked"] = [probes - len(metrics.get("leaked_probes", [])), probes]
    return out | dict(result.get("counts", {}))
