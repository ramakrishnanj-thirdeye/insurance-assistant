"""Claim-analysis dataset items (eval/datasets) for the rules and dossier tests."""

import json
from pathlib import Path
from typing import Any

from insurai.settings import ROOT

DATASETS = ROOT / "eval" / "datasets"


def load_claim_items(*names: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for name in names:
        path = DATASETS / name
        if path.exists():
            items += [
                json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
            ]
    return items


def seed_items() -> list[dict[str, Any]]:
    return load_claim_items("claim_analysis_seed.jsonl")


def all_items() -> list[dict[str, Any]]:
    return load_claim_items("claim_analysis_seed.jsonl", "claim_analysis.jsonl")


def item_ids(items: list[dict[str, Any]]) -> list[str]:
    return [i["id"] for i in items]


def write_rules(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path
