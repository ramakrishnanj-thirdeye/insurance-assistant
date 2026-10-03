"""A tiny raw dataset (same CSV layout as data/raw) for fast build and data-quality tests."""

import csv
from pathlib import Path

from insurai.settings import Settings, get_settings

Tables = dict[str, list[dict[str, object]]]

COLUMNS: dict[str, list[str]] = {
    "customers": [
        "customer_id", "customer_name", "age", "gender", "city", "state", "customer_since", "kyc_status",
        "risk_segment",
    ],
    "hospitals": ["hospital_id", "hospital_name", "city", "network_status", "specialty"],
    "policies": [
        "policy_id", "customer_id", "policy_type", "product_name", "policy_start_date", "policy_end_date",
        "sum_insured", "annual_premium", "policy_status", "co_pay_pct", "deductible", "waiting_period_days",
    ],
    "claims": [
        "claim_id", "customer_id", "policy_id", "policy_type", "claim_date", "claim_amount", "claim_status",
        "approved_amount", "diagnosis_or_loss_type", "hospital_id", "fraud_risk_score", "manual_review_flag",
        "rejection_or_adjustment_reason",
    ],
    "claim_documents": ["claim_id", "document_type", "upload_status", "verification_status", "file_type"],
    "customer_interactions": [
        "interaction_id", "customer_id", "claim_id", "interaction_date", "channel", "intent", "sentiment",
        "resolution_status",
    ],
}  # fmt: skip


def _rows(table: str, *values: tuple[object, ...]) -> list[dict[str, object]]:
    return [dict(zip(COLUMNS[table], v, strict=True)) for v in values]


TINY: Tables = {
    "customers": _rows(
        "customers",
        ("CUST1", "Asha Rao", 40, "Female", "Pune", "Maharashtra", "2020-01-01", "Verified", "Low"),
        ("CUST2", "Ravi Iyer", 55, "Male", "Delhi", "Delhi", "2019-05-01", "Verified", "Medium"),
        ("CUST3", "Asha Rao", 31, "Female", "Chennai", "Tamil Nadu", "2022-07-01", "Pending", "High"),
    ),
    "hospitals": _rows(
        "hospitals",
        ("HOSP1", "City Care 1", "Pune", "Network", "Cardiology"),
        ("HOSP2", "City Care 2", "Delhi", "Non-Network", "General"),
    ),
    "policies": _rows(
        "policies",
        # In force at as-of; deductible + co-pay exercise expected_payable.
        ("POL1", "CUST1", "Health", "Health Secure Plus", "2026-01-01", "2027-01-01", 500000, 10000, "Active",
         10, 5000, 30),
        # Recorded Active but ended: Lapsed + status_conflict; POL3 renews it the day after it ends.
        ("POL2", "CUST2", "Motor", "Two Wheeler Secure", "2024-01-01", "2025-01-01", 300000, 5000, "Active",
         0, 10000, 0),
        ("POL3", "CUST2", "Motor", "Two Wheeler Secure", "2025-01-02", "2026-01-02", 300000, 5000, "Expired",
         0, 10000, 0),
        ("POL4", "CUST3", "Travel", "Global Travel Secure", "2026-05-01", "2027-05-01", 500000, 3000,
         "Cancelled", 0, 0, 0),
    ),
    "claims": _rows(
        "claims",
        # Above sum insured, Non-Network hospital (needs Cancelled Cheque).
        ("CLM1", "CUST1", "POL1", "Health", "2026-03-01", 600000, "Approved", 450000, "Cataract", "HOSP2",
         0.1, 0, ""),
        # Below the deductible: expected_payable floors at 0. Motor claims have no hospital.
        ("CLM2", "CUST2", "POL3", "Motor", "2025-06-01", 8000, "Rejected", 0, "Theft", "", 0.7, 1,
         "Excluded"),
        ("CLM3", "CUST3", "POL4", "Travel", "2026-06-01", 20000, "Submitted", 0, "Medical Emergency", "HOSP1",
         0.3, 0, ""),
    ),
    "claim_documents": _rows(
        "claim_documents",
        ("CLM1", "Claim Form", "Uploaded", "Verified", "PDF"),
        ("CLM1", "ID Proof", "Missing", "Not Available", "PNG"),
        ("CLM1", "Hospital Bill", "Uploaded", "Pending", "PDF"),
        ("CLM1", "Discharge Summary", "Uploaded", "Rejected", "PDF"),
        ("CLM1", "Policy Copy", "Uploaded", "Verified", "PDF"),
        ("CLM2", "Claim Form", "Uploaded", "Verified", "PDF"),
        ("CLM3", "Claim Form", "Uploaded", "Verified", "PDF"),
    ),
    "customer_interactions": _rows(
        "customer_interactions",
        ("INT1", "CUST2", "CLM1", "2026-02-01", "Phone", "Claim Status", "Neutral", "Resolved"),
        ("INT2", "CUST1", "CLM1", "2026-04-01", "Email", "Claim Status", "Positive", "Pending"),
    ),
}  # fmt: skip


def write_raw(tables: Tables, raw_dir: Path) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in tables.items():
        with (raw_dir / f"{name}.csv").open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=COLUMNS[name])
            writer.writeheader()
            writer.writerows(rows)
    return raw_dir


def settings_for(base: Path, raw_dir: Path) -> Settings:
    settings = get_settings()
    paths = settings.paths.model_copy(
        update={
            "raw_dir": raw_dir,
            "warehouse": base / "out" / "warehouse.duckdb",
            "dq_report": base / "out" / "data_quality_report.json",
        }
    )
    return settings.model_copy(update={"paths": paths})
