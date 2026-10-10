"""Eval dataset lookups shared by the API and the reports (spec 11): item id -> question text."""

import json
from functools import lru_cache
from pathlib import Path

from insurai.observability import get_logger
from insurai.settings import ROOT

log = get_logger(__name__)

DATASETS = ROOT / "eval" / "datasets"


@lru_cache(maxsize=4)
def question_index(datasets: Path = DATASETS) -> dict[str, str]:
    """The user turns of every dataset item, joined with " → " for multi-turn items, keyed by item id."""
    out: dict[str, str] = {}
    for path in sorted(datasets.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                log.warning("skipping an unreadable line in %s", path.name)
                continue
            turns = [t.get("content", "") for t in item.get("turns", []) if t.get("role") == "user"]
            if item.get("id") and turns:
                out.setdefault(str(item["id"]), " → ".join(turns))
    return out
