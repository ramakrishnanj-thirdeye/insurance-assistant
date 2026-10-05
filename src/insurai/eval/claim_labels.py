"""Draft claim_analysis items with labels derived independently of the rules engine (spec 11, M5).

python -m insurai.eval.claim_labels            # write eval/datasets/claim_analysis.jsonl + the checklist

The labels are recomputed in plain Python from silver.* (claims, policies, customers, hospitals,
claim_documents) and ref.* (required documents, coverage grid): dates, the expected payable, the document
checklist and every rule's status are derived here, without gold.claim_facts or insurai.rules, so the
rules-engine tests compare two implementations. Items are tagged `draft` until a person signs off each one
in eval/datasets/claim_analysis_checklist.md.
"""

import argparse
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from insurai import db
from insurai.observability import get_logger
from insurai.settings import ROOT, get_settings

log = get_logger(__name__)

DATASETS = ROOT / "eval" / "datasets"
OUT = DATASETS / "claim_analysis.jsonl"
CHECKLIST = DATASETS / "claim_analysis_checklist.md"
FIRST_ID = 4  # CA001-CA003 are the hand-labelled seed items
PAID = ("Approved", "Partially Approved")
BLOCKERS = ("R01", "R02", "R03", "R04", "R05", "R06", "R07")  # configured severity blocker (spec 07)

ROWS_SQL = """
SELECT c.claim_id, c.customer_id, c.policy_id, c.policy_type, c.product_name, c.claim_date, c.claim_amount,
       c.claim_status, c.approved_amount, c.diagnosis_or_loss_type, c.hospital_id, c.fraud_risk_score,
       c.manual_review_flag, c.rejection_or_adjustment_reason,
       p.policy_start_date, p.policy_end_date, p.policy_status, p.sum_insured, p.co_pay_pct, p.deductible,
       p.waiting_period_days, p.continuous_cover_start,
       cu.kyc_status, h.network_status
FROM silver.claims c
JOIN silver.policies p ON p.policy_id = c.policy_id
JOIN silver.customers cu ON cu.customer_id = c.customer_id
LEFT JOIN silver.hospitals h ON h.hospital_id = c.hospital_id
ORDER BY c.claim_id
"""


@dataclass
class Derived:
    row: dict[str, Any]
    rules: dict[str, str]
    missing: list[str]
    pending: list[str]
    rejected: list[str]
    consistency: list[str]
    expected_payable: int

    @property
    def needs_review(self) -> bool:
        escalate = ("R10", "R11", "R12")
        return any(
            s == "review" or (s == "fail" and (r in BLOCKERS or r in escalate)) for r, s in self.rules.items()
        )

    @property
    def blocker_fails(self) -> int:
        return sum(self.rules[r] == "fail" for r in BLOCKERS)


def _status(applies: bool, passes: bool, review: bool = False) -> str:
    if not applies:
        return "not_applicable"
    return "pass" if passes else ("review" if review else "fail")


def expected_payable(r: dict[str, Any]) -> int:
    base = max(0, min(r["claim_amount"], r["sum_insured"]) - r["deductible"])
    value = Decimal(base) * (1 - Decimal(r["co_pay_pct"]) / 100)
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def required_docs(
    r: dict[str, Any], required: list[tuple[str, str, str | None, list[str] | None]]
) -> list[str]:
    out = []
    for policy_type, doc, field, values in required:
        if policy_type != r["policy_type"]:
            continue
        if field is None or (field in r and r[field] in (values or [])):
            out.append(doc)
    return sorted(set(out))


def derive(
    r: dict[str, Any],
    docs: dict[str, tuple[str | None, str | None]],
    required: list[tuple[str, str, str | None, list[str] | None]],
    coverage: dict[tuple[str, str], dict[str, Any]],
    thresholds: dict[str, float],
) -> Derived:
    claim_date: date = r["claim_date"]
    dsps = (claim_date - r["policy_start_date"]).days
    cover_start = r["continuous_cover_start"]
    dscs = (claim_date - cover_start).days if cover_start else None
    cov = coverage.get((r["product_name"], r["diagnosis_or_loss_type"]), {})
    status = cov.get("coverage_status")
    req_wait = cov.get("required_waiting_days") or 0
    payable = expected_payable(r)

    need = required_docs(r, required)
    missing = [d for d in need if d not in docs or docs[d][0] == "Missing"]
    present = [d for d in need if d not in missing]
    pending = [d for d in present if docs[d][1] == "Pending"]
    rejected = [d for d in present if docs[d][1] == "Rejected"]

    rules = {
        "R01": _status(True, r["policy_start_date"] <= claim_date <= r["policy_end_date"]),
        "R02": _status(True, r["policy_status"] is not None and r["policy_status"] != "Cancelled"),
        "R03": _status(r["waiting_period_days"] > 0 and dsps >= 0, dsps >= r["waiting_period_days"]),
        "R04": _status(
            req_wait > 0 and dscs is not None and dscs >= 0, dscs is not None and dscs >= req_wait
        ),
        "R05": _status(
            True, status == "covered", status in ("needs_review", "conditional") or status is None
        ),
        "R06": _status(True, not missing),
        "R07": _status(True, not pending and not rejected, not rejected),
        "R08": _status(
            r["policy_type"] == "Health" and r["hospital_id"] is not None, r["network_status"] == "Network"
        ),
        "R09": _status(
            r["claim_status"] in PAID,
            r["approved_amount"] <= payable and r["approved_amount"] <= r["sum_insured"],
        ),
        "R10": _status(
            True,
            r["fraud_risk_score"] is not None and r["fraud_risk_score"] < thresholds["fraud_review_score"],
        ),
        "R11": _status(True, not r["claim_amount"] > thresholds["high_value_inr"]),
        "R12": _status(True, r["manual_review_flag"] == 0 and r["kyc_status"] == "Verified"),
    }
    blocker_fail = any(rules[b] == "fail" for b in BLOCKERS)
    within_wait = 0 <= dsps <= r["waiting_period_days"] - 1
    reason = r["rejection_or_adjustment_reason"]
    flags = {
        "C1": r["claim_status"] in PAID and blocker_fail,
        "C2": r["claim_status"] == "Pending Documents" and not missing and not pending,
        "C3": reason == "Insufficient documents" and not missing,
        "C4": reason == "Waiting period not completed" and not within_wait and dsps >= 0,
    }
    return Derived(r, rules, missing, pending, rejected, [c for c, on in flags.items() if on], payable)


@dataclass
class Pattern:
    key: str
    title: str
    question: str
    test: Callable[[Derived], bool]
    must_mention: Callable[[Derived], list[str]]


def _docs_mention(d: Derived) -> list[str]:
    return d.missing[:2] + d.rejected[:1]


PATTERNS = [
    Pattern(
        "cancelled",
        "Cancelled policy (R02 fail)",
        "Analyze claim {claim_id}.",
        lambda d: d.rules["R02"] == "fail" and d.rules["R01"] == "pass",
        lambda d: ["Cancelled", *_docs_mention(d)],
    ),
    Pattern(
        "schedule_wait",
        "Schedule waiting period not met (R03 fail)",
        "Assess claim {claim_id} for approval.",
        lambda d: d.rules["R03"] == "fail" and d.rules["R01"] == "pass",
        lambda d: ["waiting period", str(d.row["waiting_period_days"]), *_docs_mention(d)],
    ),
    Pattern(
        "maternity_wait",
        "Maternity inside its 24-month wait (R04 fail)",
        "Analyze claim {claim_id}.",
        lambda d: d.row["diagnosis_or_loss_type"] == "Maternity" and d.rules["R04"] == "fail",
        lambda d: ["Maternity", "730", *_docs_mention(d)],
    ),
    Pattern(
        "maternity_excluded_paid",
        "Maternity paid on a product that excludes it (R05 fail + C1)",
        "Review claim {claim_id}.",
        lambda d: (
            d.row["diagnosis_or_loss_type"] == "Maternity"
            and d.row["claim_status"] in PAID
            and d.rules["R05"] == "fail"
            and "C1" in d.consistency
        ),
        lambda d: ["Maternity", d.row["product_name"], "not cover", *_docs_mention(d)],
    ),
    Pattern(
        "rejected_document",
        "Rejected required document (R07 fail)",
        "Analyze claim {claim_id}.",
        lambda d: d.rules["R07"] == "fail" and d.rules["R01"] == "pass",
        lambda d: ["rejected", *d.rejected, *d.missing[:1]],
    ),
    Pattern(
        "escalation",
        "Escalation by fraud score (R10 fail)",
        "Evaluate claim {claim_id}.",
        lambda d: d.rules["R10"] == "fail" and d.rules["R01"] == "pass",
        lambda d: ["fraud risk score", "manual review queue", *_docs_mention(d)],
    ),
]
CONTROL = Pattern(
    "control",
    "Control: fewest blocker fails in the data",
    "Give me a summary of claim {claim_id}.",
    lambda d: True,
    lambda d: [d.row["claim_status"]],  # no findings: the narrative must still state the status
)


def load(con: Any) -> list[Derived]:
    cur = con.execute(ROWS_SQL)
    cols = [c[0] for c in cur.description]
    rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
    docs: dict[str, dict[str, tuple[str | None, str | None]]] = {}
    for claim_id, doc_type, upload, verification in con.execute(
        "SELECT claim_id, document_type, upload_status, verification_status FROM silver.claim_documents"
    ).fetchall():
        docs.setdefault(claim_id, {})[doc_type] = (upload, verification)
    required = [tuple(r) for r in con.execute("SELECT * FROM ref.required_documents").fetchall()]
    coverage = {
        (r[0], r[1]): {"coverage_status": r[2], "required_waiting_days": r[3]}
        for r in con.execute(
            "SELECT product_name, diagnosis, coverage_status, required_waiting_days "
            "FROM ref.diagnosis_coverage"
        ).fetchall()
    }
    thresholds = {k: float(v) for k, v in get_settings().thresholds.model_dump().items()}
    return [derive(r, docs.get(r["claim_id"], {}), required, coverage, thresholds) for r in rows]  # type: ignore[arg-type]


def pick(derived: list[Derived]) -> list[tuple[Pattern, Derived]]:
    chosen: list[tuple[Pattern, Derived]] = []
    used: set[str] = set()
    for pattern in PATTERNS:
        hit = next(d for d in derived if pattern.test(d) and d.row["claim_id"] not in used)
        chosen.append((pattern, hit))
        used.add(hit.row["claim_id"])
    control = min((d for d in derived if d.row["claim_id"] not in used), key=lambda d: d.blocker_fails)
    chosen.append((CONTROL, control))
    return chosen


def item(n: int, pattern: Pattern, d: Derived) -> dict[str, Any]:
    r = d.row
    claim_id = r["claim_id"]
    return {
        "id": f"CA{n:03d}",
        "slice": "claim_analysis",
        "persona": "claims_agent",
        "turns": [{"role": "user", "content": pattern.question.format(claim_id=claim_id)}],
        "expected_route": ["claim_analysis"],
        "expected_entities": {"claim_id": claim_id},
        "gold_answer": None,
        "gold_sources": [f"claims:{claim_id}"],
        "gold_sql": None,
        "must_refuse": False,
        "tags": ["draft", "derived", pattern.key],
        "labels": {
            "claim_id": claim_id,
            "pattern": pattern.title,
            "facts": {
                "product_name": r["product_name"],
                "diagnosis_or_loss_type": r["diagnosis_or_loss_type"],
                "claim_status": r["claim_status"],
                "claim_amount": r["claim_amount"],
                "approved_amount": r["approved_amount"],
                "expected_payable": d.expected_payable,
                "claim_date": r["claim_date"].isoformat(),
                "policy_start_date": r["policy_start_date"].isoformat(),
                "policy_end_date": r["policy_end_date"].isoformat(),
            },
            "expected_rules": d.rules,
            "expected_missing": d.missing,
            "expected_pending": d.pending,
            "expected_rejected": d.rejected,
            "expected_consistency": d.consistency,
            "needs_human_review": d.needs_review,
            "must_mention": list(dict.fromkeys(pattern.must_mention(d))),
        },
    }


def checklist(items: list[dict[str, Any]]) -> str:
    lines = [
        "# claim_analysis draft items: sign-off checklist",
        "",
        "Labels were derived by `python -m insurai.eval.claim_labels` from silver.* and ref.* in",
        "plain Python, independently of the rules engine. Check each claim against the raw data, then",
        "tick the box and remove the `draft` tag from the item in claim_analysis.jsonl.",
        "",
    ]
    for it in items:
        lab = it["labels"]
        failing = [f"{k} {v}" for k, v in lab["expected_rules"].items() if v in ("fail", "review")]
        lines += [
            f"## {it['id']} {lab['claim_id']}: {lab['pattern']}",
            "",
            f'- Question: "{it["turns"][0]["content"]}"',
            f"- Facts: {json.dumps(lab['facts'], ensure_ascii=False)}",
            f"- Failing or review rules: {', '.join(failing) or 'none'}",
            f"- Missing: {', '.join(lab['expected_missing']) or 'none'}; pending: "
            f"{', '.join(lab['expected_pending']) or 'none'}; "
            f"rejected: {', '.join(lab['expected_rejected']) or 'none'}",
            f"- Consistency flags: {', '.join(lab['expected_consistency']) or 'none'}; "
            f"needs human review: {lab['needs_human_review']}",
            f"- Must mention: {', '.join(lab['must_mention'])}",
            "- [ ] Signed off (name, date):",
            "",
        ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="insurai.eval.claim_labels")
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--checklist", type=Path, default=CHECKLIST)
    args = parser.parse_args(argv)
    with db.connect(read_only=True) as con:
        derived = load(con)
    items = [item(FIRST_ID + n, p, d) for n, (p, d) in enumerate(pick(derived))]
    args.out.write_text(
        "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items), encoding="utf-8", newline="\n"
    )
    args.checklist.write_text(checklist(items), encoding="utf-8", newline="\n")
    log.info("wrote %d draft items to %s and the checklist to %s", len(items), args.out, args.checklist)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
