"""Judge calibration (spec 11 Judge, AC-11-06): human scores against the correctness judge, and the V7
judge's precision on the claims it marked unsupported.

eval/datasets/judge_calibration.md is built once, by the first full run (never rebuilt once a box is filled):
- Part A: 10 answers sampled with seed 42 (6 from policy_clauses_e2e, 4 from claim_analysis), each with the
  question, the gold answer, the system's answer (frozen) and an empty 1–5 score box;
- Part B: the claims the V7 judge marked unsupported in claim_analysis and the full-graph slices, at most 15
  (sampled with seed 42 when there are more), each marked by a person as a correct verdict or a false
  positive.
The frozen items live in eval/calibration/items.json. Every full run re-scores the Part A answers with the
judge into eval/calibration/judge_scores.json, which no report shows; until every Part A box is filled, report
rows for those items carry `judge_score: "sealed"`. Then agreement (|judge − human| ≤ 1) is reported with
counts and an interval; below 80% the report is marked "judge uncalibrated". V7 precision is correct ÷
(correct + false positive) over the marked Part B items, reported with the sampled n.

`python -m insurai.eval.calibration --score` recomputes the status from the file without a full run.
"""

import argparse
import json
import random
import re
from pathlib import Path
from typing import Any

from insurai.eval import claim_analysis, correctness
from insurai.eval.e2e import CLAUSES_SLICE, load_items
from insurai.eval.stats import fmt_prop, ratio, wilson
from insurai.observability import get_logger
from insurai.settings import ROOT

log = get_logger(__name__)

CAL_MD = ROOT / "eval" / "datasets" / "judge_calibration.md"
CAL_DIR = ROOT / "eval" / "calibration"
SEED = 42
PART_A = {CLAUSES_SLICE: 6, claim_analysis.SLICE: 4}
PART_B_CAP = 15
V7_SLICES = (claim_analysis.SLICE, CLAUSES_SLICE, "comparisons", "adversarial", "guardrails")
AGREEMENT_MIN = 0.80
WITHIN = 1
SEALED = "sealed"

_SCORE_BOX = re.compile(r"^### (CAL\d+)\b.*?\*\*Your score \(1–5\):\*\* \[\s*([1-5]?)\s*\]", re.S | re.M)
_V7_BLOCK = re.compile(r"^### (V7-\d+)\b(.*?)(?=^### |\Z)", re.S | re.M)
_MARK = re.compile(r"^- \[([ xX])\] (correct|false positive)\b", re.M)


class CalibrationLocked(RuntimeError):
    """The calibration file already has human marks; it is never rebuilt over them."""


# --- build -------------------------------------------------------------------------------------------


def _clause_golds() -> dict[str, tuple[str, str]]:
    items = load_items("seed_rag.jsonl", "policy_clauses") + load_items(
        "policy_clauses.jsonl", "policy_clauses"
    )
    return {i.id: (i.question, i.gold_answer) for i in items if i.gold_answer}


def _claim_golds() -> dict[str, tuple[str, str]]:
    return {
        i.id: (i.question, claim_analysis.gold_from_labels(i.labels)) for i in claim_analysis.load_items()
    }


def part_a_candidates(results: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Judged rows with an answer, per Part A slice, as frozen items (question, gold, answer)."""
    golds = {CLAUSES_SLICE: _clause_golds(), claim_analysis.SLICE: _claim_golds()}
    answer_key = {CLAUSES_SLICE: "answer", claim_analysis.SLICE: "narrative"}
    out: dict[str, list[dict[str, Any]]] = {}
    for slice_name in PART_A:
        rows = results.get(slice_name, {}).get("items", [])
        out[slice_name] = [
            {
                "slice": slice_name,
                "item_id": r["id"],
                "question": golds[slice_name][r["id"]][0],
                "gold": golds[slice_name][r["id"]][1],
                "answer": r[answer_key[slice_name]],
            }
            for r in rows
            if r["id"] in golds[slice_name] and r.get(answer_key[slice_name]) and "judge_score" in r
        ]
    return out


def sample_part_a(candidates: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rng = random.Random(SEED)
    picked: list[dict[str, Any]] = []
    for slice_name, n in PART_A.items():
        pool = candidates.get(slice_name, [])
        picked += rng.sample(pool, min(n, len(pool)))
    short = sum(PART_A.values()) - len(picked)
    rest = [c for pool in candidates.values() for c in pool if c not in picked]
    picked += rng.sample(rest, min(short, len(rest)))  # a slice with too few answers: fill from the other
    return [{"id": f"CAL{k:02d}", **item} for k, item in enumerate(picked, start=1)]


def sample_part_b(results: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """(at most PART_B_CAP V7 items, how many unsupported claims there were in all)."""
    pool = []
    for slice_name in V7_SLICES:
        for r in results.get(slice_name, {}).get("items", []):
            for claim in r.get("v7_unsupported") or []:
                pool.append(
                    {
                        "slice": slice_name,
                        "item_id": r["id"],
                        "claim": claim,
                        "answer": r.get("answer") or r.get("narrative") or "",
                        "evidence": r.get("v7_evidence_text", ""),
                    }
                )
    picked = random.Random(SEED).sample(pool, PART_B_CAP) if len(pool) > PART_B_CAP else pool
    return [{"id": f"V7-{k:02d}", **item} for k, item in enumerate(picked, start=1)], len(pool)


def build(results: dict[str, Any], md: Path | None = None, cal_dir: Path | None = None) -> bool:
    """Write the calibration file and frozen items from a full run's results when absent; False if present."""
    md, cal_dir = md or CAL_MD, cal_dir or CAL_DIR
    items_path = cal_dir / "items.json"
    if items_path.exists() and md.exists():
        return False
    if md.exists() and any_marks(md.read_text(encoding="utf-8")):
        raise CalibrationLocked(f"{md} has human marks; not rebuilding it")
    part_a = sample_part_a(part_a_candidates(results))
    part_b, total = sample_part_b(results)
    cal_dir.mkdir(parents=True, exist_ok=True)
    frozen = {"seed": SEED, "part_a": part_a, "part_b": part_b, "part_b_total": total}
    items_path.write_text(json.dumps(frozen, indent=2, ensure_ascii=False), encoding="utf-8")
    md.write_text(render_md(part_a, part_b, total), encoding="utf-8")
    log.info("calibration file written: %d Part A items, %d of %d V7 items", len(part_a), len(part_b), total)
    return True


def render_md(part_a: list[dict[str, Any]], part_b: list[dict[str, Any]], total: int) -> str:
    lines = [
        "# Judge calibration (spec 11, AC-11-06)",
        "",
        "Fill in every box, then run `uv run python -m insurai.eval.calibration --score`",
        "(or the next full run). The judge's scores stay sealed in eval/calibration/judge_scores.json",
        "until every Part A box is filled.",
        "",
        "## Part A: answer correctness (score 1–5)",
        "",
        "5 = fully correct and complete; 4 = correct with minor omissions; 3 = partly correct;",
        "2 = mostly wrong; 1 = wrong or refuses without reason.",
        "Agreement counts a judge score within ±1 of yours.",
        "",
    ]
    for item in part_a:
        lines += [
            f"### {item['id']} · {item['slice']} {item['item_id']}",
            "",
            f"**Question:** {item['question']}",
            "",
            f"**Gold answer:** {item['gold']}",
            "",
            "**System answer:**",
            "",
            *[f"> {line}" if line else ">" for line in item["answer"].splitlines()],
            "",
            "**Your score (1–5):** [ ]",
            "",
        ]
    lines += [
        f'## Part B: V7 "unsupported" verdicts ({len(part_b)} of {total}, seed {SEED})',
        "",
        "The V7 judge marked each claim below unsupported by the evidence. Tick one box per item: `correct`",
        "if the evidence really does not support the claim, `false positive` if it does.",
        "",
    ]
    for item in part_b:
        lines += [
            f"### {item['id']} · {item['slice']} {item['item_id']}",
            "",
            f"**Claim:** {item['claim']}",
            "",
            "<details><summary>Answer</summary>",
            "",
            *[f"> {line}" if line else ">" for line in item["answer"].splitlines()],
            "",
            "</details>",
            "",
            "<details><summary>Evidence the judge saw</summary>",
            "",
            "```",
            item["evidence"] or "(not recorded)",
            "```",
            "",
            "</details>",
            "",
            "- [ ] correct (the claim is unsupported)",
            "- [ ] false positive (the evidence supports it)",
            "",
        ]
    return "\n".join(lines)


# --- human marks -------------------------------------------------------------------------------------


def human_scores(text: str) -> dict[str, int | None]:
    return {m.group(1): int(m.group(2)) if m.group(2) else None for m in _SCORE_BOX.finditer(text)}


def v7_marks(text: str) -> dict[str, str | None]:
    """V7 item -> "correct", "false positive", or None (unmarked, or both boxes ticked)."""
    out: dict[str, str | None] = {}
    for block in _V7_BLOCK.finditer(text):
        ticked = [m.group(2) for m in _MARK.finditer(block.group(2)) if m.group(1) in "xX"]
        out[block.group(1)] = ticked[0] if len(ticked) == 1 else None
    return out


def any_marks(text: str) -> bool:
    return any(v is not None for v in human_scores(text).values()) or any(
        v is not None for v in v7_marks(text).values()
    )


# --- judge and status --------------------------------------------------------------------------------


def frozen_items(cal_dir: Path | None = None) -> dict[str, Any] | None:
    path = (cal_dir or CAL_DIR) / "items.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def judge_part_a(cal_dir: Path | None = None) -> dict[str, int]:
    """Re-score the frozen Part A answers with the judge into the sealed scores file."""
    cal_dir = cal_dir or CAL_DIR
    frozen = frozen_items(cal_dir)
    if frozen is None:
        return {}
    scores: dict[str, int] = {}
    for item in frozen["part_a"]:
        try:
            scores[item["id"]] = correctness.judge_correctness(
                item["question"], item["gold"], item["answer"]
            ).score
        except Exception:  # an unscored item is left out of agreement
            log.exception("calibration judge failed on %s", item["id"])
    (cal_dir / "judge_scores.json").write_text(json.dumps(scores, indent=2), encoding="utf-8")
    return scores


def status(md: Path | None = None, cal_dir: Path | None = None) -> dict[str, Any]:
    """Agreement and V7 precision once the human marks are in; otherwise what is still awaited."""
    md, cal_dir = md or CAL_MD, cal_dir or CAL_DIR
    frozen = frozen_items(cal_dir)
    if frozen is None or not md.exists():
        return {"status": "no calibration file yet"}
    text = md.read_text(encoding="utf-8")
    human = human_scores(text)
    scored = {k: v for k, v in human.items() if v is not None}
    part_a: dict[str, Any] = {"items": len(human), "human_scored": len(scored)}
    if len(scored) < len(human) or not human:
        part_a["status"] = "awaiting human scores"
    else:
        path = cal_dir / "judge_scores.json"
        judge = (
            {k: int(v) for k, v in json.loads(path.read_text(encoding="utf-8")).items()}
            if path.exists()
            else {}
        )
        pairs = [(scored[k], judge[k]) for k in scored if k in judge]
        k = sum(abs(h - j) <= WITHIN for h, j in pairs)
        part_a |= {"status": "scored", "agreement": ratio(k, len(pairs)), "counts": [k, len(pairs)]}
    marks = v7_marks(text)
    marked = [v for v in marks.values() if v is not None]
    part_b: dict[str, Any] = {"sampled": len(marks), "total": frozen.get("part_b_total", len(marks))}
    if len(marked) < len(marks):
        part_b |= {"status": "awaiting marks", "marked": len(marked)}
    else:
        k = sum(v == "correct" for v in marked)
        part_b |= {"status": "scored", "precision": ratio(k, len(marked)), "counts": [k, len(marked)]}
    out = {"part_a": part_a, "part_b": part_b}
    agreement = part_a.get("agreement")
    out["uncalibrated"] = agreement is not None and agreement < AGREEMENT_MIN
    return out


def sealed_ids(cal_dir: Path | None = None, md: Path | None = None) -> set[tuple[str, str]]:
    """(slice, item id) of Part A items while their judge scores are sealed."""
    frozen = frozen_items(cal_dir)
    if frozen is None or status(md, cal_dir).get("part_a", {}).get("status") == "scored":
        return set()
    return {(i["slice"], i["item_id"]) for i in frozen["part_a"]}


def seal(results: dict[str, Any], cal_dir: Path | None = None, md: Path | None = None) -> None:
    """Replace the judge's per-item scores of sealed calibration items in the report rows."""
    sealed = sealed_ids(cal_dir, md)
    for slice_name, result in results.items():
        for row in result.get("items", []):
            if isinstance(row, dict) and (slice_name, row.get("id")) in sealed and "judge_score" in row:
                row["judge_score"] = row["judge_reason"] = SEALED


def describe(state: dict[str, Any]) -> list[str]:
    """Report lines for the calibration status."""
    if "part_a" not in state:
        return [state.get("status", "no calibration")]
    a, b = state["part_a"], state["part_b"]
    lines = []
    if a.get("status") == "scored":
        k, n = a["counts"]
        lines.append(f"Judge agreement (within ±{WITHIN}): {fmt_prop(k, n)}")
    else:
        lines.append(f"Judge agreement: {a['status']} ({a['human_scored']} of {a['items']} scored)")
    if b.get("status") == "scored":
        k, n = b["counts"]
        lines.append(
            f"V7 precision: {fmt_prop(k, n)} (sampled {b['sampled']} of {b['total']} unsupported claims)"
        )
    else:
        lines.append(f"V7 precision: {b['status']} ({b.get('marked', 0)} of {b['sampled']} marked)")
    if state.get("uncalibrated"):
        lines.append(f"**judge uncalibrated** (agreement below {AGREEMENT_MIN:.0%})")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="insurai.eval.calibration")
    parser.add_argument("--score", action="store_true", required=True, help="recompute from the file")
    parser.parse_args(argv)
    state = status()
    for line in describe(state):
        log.info("%s", line)
    if "part_a" in state and state["part_a"].get("counts"):
        k, n = state["part_a"]["counts"]
        log.info("agreement interval: %.2f–%.2f", *wilson(k, n))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
