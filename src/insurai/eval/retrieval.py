"""Retrieval evaluation on the policy_clauses slice: spec 11 metrics, ablation configs A–E (spec 04).

Config F (+LLM rewrite) is deferred with the rewrite stage (3-day scope).
"""

import json
import math
import subprocess
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from insurai.observability import get_logger
from insurai.retrieval.schemas import RetrievalConfig, RetrievalResult
from insurai.retrieval.search import search_policy
from insurai.settings import ROOT, get_settings
from insurai.tools.schemas import ToolContext

log = get_logger(__name__)

DATASETS = ROOT / "eval" / "datasets"
SLICE_FILES = ("seed_rag.jsonl", "policy_clauses.jsonl")
SLICE = "policy_clauses"
UNANSWERABLE = "unanswerable"
TOP_K = 5

CONFIGS: dict[str, RetrievalConfig] = {
    "A": RetrievalConfig(use_dense=True, use_sparse=False, use_filter=False, use_rerank=False),
    "B": RetrievalConfig(use_dense=False, use_sparse=True, use_filter=False, use_rerank=False),
    "C": RetrievalConfig(use_dense=True, use_sparse=True, use_filter=False, use_rerank=False),
    "D": RetrievalConfig(use_dense=True, use_sparse=True, use_filter=True, use_rerank=False),
    "E": RetrievalConfig(use_dense=True, use_sparse=True, use_filter=True, use_rerank=True),
}
DESCRIPTIONS = {"A": "dense-only", "B": "bm25-only", "C": "hybrid", "D": "+filter", "E": "+rerank"}
DEFERRED = ["F (+rewrite): 3-day scope"]

SearchFn = Callable[[ToolContext, str, str | None, RetrievalConfig], RetrievalResult]


class EvalItem(BaseModel):
    id: str
    question: str
    product: str | None
    gold_sources: list[str]
    unanswerable: bool = False


def load_policy_slice(datasets: Path = DATASETS) -> list[EvalItem]:
    items: list[EvalItem] = []
    for name in SLICE_FILES:
        for line in (datasets / name).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row["slice"] != SLICE:
                continue
            items.append(
                EvalItem(
                    id=row["id"],
                    question=row["turns"][0]["content"],
                    product=row["expected_entities"].get("product"),
                    gold_sources=row["gold_sources"],
                    unanswerable=UNANSWERABLE in row.get("tags", []),
                )
            )
    return items


def recall_at_k(labels: list[str], gold: list[str], k: int = TOP_K) -> float:
    """1 if any gold label is among the top k retrieved labels."""
    wanted = {_bare(g) for g in gold}
    return 1.0 if any(_bare(label) in wanted for label in labels[:k]) else 0.0


def product_precision_at_k(products: list[str], gold_product: str, k: int = TOP_K) -> float:
    """Share of the top k chunks whose product is the gold product or ALL."""
    top = products[:k]
    return sum(p in (gold_product, "ALL") for p in top) / len(top) if top else 0.0


def mrr(labels: list[str], gold: list[str], depth: int = 20) -> float:
    """1 / rank of the first gold label, 0 if absent in the top `depth`."""
    wanted = {_bare(g) for g in gold}
    for rank, label in enumerate(labels[:depth], start=1):
        if _bare(label) in wanted:
            return 1 / rank
    return 0.0


def tune_threshold(answerable: list[float], unanswerable: list[float]) -> tuple[float, float]:
    """Threshold on the top rerank score maximising F1 of "answerable" (score ≥ t); lowest on ties.

    Candidates are midpoints between consecutive distinct scores, so the threshold sits in a gap.
    """
    scores = sorted(set(answerable) | set(unanswerable))
    candidates = [scores[0] - 1.0] + [(a + b) / 2 for a, b in zip(scores, scores[1:], strict=False)]
    best_t, best_f1 = candidates[0], -1.0
    for t in candidates:
        tp = sum(s >= t for s in answerable)
        fp = sum(s >= t for s in unanswerable)
        fn = len(answerable) - tp
        f1 = 2 * tp / (2 * tp + fp + fn) if tp else 0.0
        if f1 > best_f1:
            best_t, best_f1 = t, f1
    return round(best_t, 4), round(best_f1, 4)


def run_config(
    items: list[EvalItem],
    cfg: RetrievalConfig,
    search_fn: SearchFn | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Score one config. Retrieval runs to depth prefetch_k (for MRR); recall and precision use the top 5."""
    search = search_fn or _search
    deep = cfg.model_copy(update={"final_k": cfg.prefetch_k})
    as_of = as_of or get_settings().as_of_date
    if items:  # warm-up: model sessions and the index load outside the latency figures
        search(_ctx(items[0], as_of), items[0].question, items[0].product, deep)

    rows: list[dict[str, Any]] = []
    for item in items:
        result = search(_ctx(item, as_of), item.question, item.product, deep)
        hits = [r for r in result.chunks if r.via == "search"]
        labels = [r.chunk.citation_label for r in hits]
        row: dict[str, Any] = {
            "id": item.id,
            "unanswerable": item.unanswerable,
            "product": item.product,
            "gold": item.gold_sources,
            "top5": labels[:TOP_K],
            "confident": result.confident,
            "top_score": hits[0].rerank_score if hits else None,
            "latency_ms": result.timings_ms.get("total", 0.0),
        }
        if not item.unanswerable:
            row["recall_at_5"] = recall_at_k(labels, item.gold_sources)
            row["mrr"] = mrr(labels, item.gold_sources)
            if item.product:
                row["product_precision_at_5"] = product_precision_at_k(
                    [r.chunk.product for r in hits], item.product
                )
        rows.append(row)
    return {"config": cfg.model_dump(), "metrics": _summarise(rows, cfg), "items": rows}


def run_ablation(
    items: list[EvalItem],
    search_fn: SearchFn | None = None,
    out_dir: Path | None = None,
    as_of: date | None = None,
) -> Path:
    """Run configs A–E and write eval/reports/ablation_<ts>.json."""
    configs = {
        name: {"description": DESCRIPTIONS[name], **run_config(items, cfg, search_fn, as_of)}
        for name, cfg in CONFIGS.items()
    }
    for name, c in configs.items():
        log.info("config %s %-10s %s", name, DESCRIPTIONS[name], c["metrics"])
    return write_report("ablation", {"configs": configs, "deferred": DEFERRED}, out_dir)


def write_report(suite: str, body: dict[str, Any], out_dir: Path | None = None) -> Path:
    out_dir = out_dir or get_settings().paths.eval_reports
    out_dir.mkdir(parents=True, exist_ok=True)
    created = datetime.now(UTC)  # report metadata, not business logic (hard rule 5 covers the as-of date)
    report = {
        "suite": suite,
        "created_at": created.isoformat(timespec="seconds"),
        "git_sha": _git_sha(),
        "retrieval_settings": get_settings().retrieval.model_dump(),
        **body,
    }
    path = out_dir / f"{suite}_{created:%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("report written to %s", path)
    return path


def _summarise(rows: list[dict[str, Any]], cfg: RetrievalConfig) -> dict[str, Any]:
    answerable = [r for r in rows if not r["unanswerable"]]
    probes = [r for r in rows if r["unanswerable"]]
    latencies = sorted(r["latency_ms"] for r in rows)
    metrics: dict[str, Any] = {
        "items": len(answerable),
        "probes": len(probes),
        "recall_at_5": _mean(r["recall_at_5"] for r in answerable),
        "product_precision_at_5": _mean(
            r["product_precision_at_5"] for r in answerable if "product_precision_at_5" in r
        ),
        "mrr": _mean(r["mrr"] for r in answerable),
        "latency_p50_ms": _percentile(latencies, 0.50),
        "latency_p95_ms": _percentile(latencies, 0.95),
        "probes_not_confident": sum(not r["confident"] for r in probes),
        "answerable_not_confident": sum(not r["confident"] for r in answerable),
        "misses": [r["id"] for r in answerable if r["recall_at_5"] == 0.0],
    }
    if cfg.use_rerank and answerable and probes:
        threshold, f1 = tune_threshold([r["top_score"] for r in answerable], [r["top_score"] for r in probes])
        metrics["suggested_rerank_threshold"] = threshold
        metrics["suggested_threshold_f1"] = f1
    return metrics


def _search(ctx: ToolContext, query: str, product: str | None, cfg: RetrievalConfig) -> RetrievalResult:
    return search_policy(ctx, query, product=product, cfg=cfg)


def _ctx(item: EvalItem, as_of: date) -> ToolContext:
    return ToolContext(persona="claims_agent", as_of=as_of, trace_id=f"eval-{item.id}")


def _bare(label: str) -> str:
    return label.strip().strip("[]")


def _mean(values: Any) -> float:
    values = list(values)
    return round(sum(values) / len(values), 4) if values else 0.0


def _percentile(sorted_values: list[float], q: float) -> float:
    """Nearest-rank percentile."""
    if not sorted_values:
        return 0.0
    return sorted_values[max(0, math.ceil(q * len(sorted_values)) - 1)]


def _git_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip()
