"""Coverage matrix loader and the product × diagnosis grid.

Spec 03 owns it; spec 01 uses `coverage_grid` to build ref.diagnosis_coverage.
"""

from pathlib import Path
from typing import NamedTuple

import yaml

from insurai.knowledge.schemas import STAR, Basis, CoverageGridRow, CoverageMatrix, CoverageOverride
from insurai.observability import get_logger

log = get_logger(__name__)

WAITING_SECTION = 4
ACCIDENT_EXEMPT = "A1_accident_exempt"
SPECIFIED_DISEASES = "A2_specified_diseases"


class _Wait(NamedTuple):
    days: int
    basis: Basis
    reason: str


def load_coverage(path: Path) -> CoverageMatrix:
    matrix = CoverageMatrix.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    if matrix.status != "reviewed":
        log.warning("coverage matrix %s has status %r (AC-03-06 review pending)", path.name, matrix.status)
    return matrix


def coverage_grid(m: CoverageMatrix) -> list[CoverageGridRow]:
    """Expand the matrix into one row per product × diagnosis of its policy type (spec 01 §Reference tables).

    1. Status starts at default_status.
    2. Waits: product initial days (document), specified-disease months for assumption A2 diagnoses
       (assumption), condition waits from overrides (their basis).
    3. Overrides apply in file order, so a specific diagnosis listed after "*" beats it.
    4. A1 (accident-exempt) diagnoses get no wait.
    5. The largest wait wins and carries its basis and reason.
    """
    dc = m.diagnosis_coverage
    exempt = dc.assumption(ACCIDENT_EXEMPT)
    specified = dc.assumption(SPECIFIED_DISEASES)
    rows: list[CoverageGridRow] = []
    for product, spec in m.products.items():
        waiting = spec.waiting
        for diagnosis in dc.diagnoses[spec.policy_type]:
            status, section, basis, reason = dc.default_status, None, "document", None
            waits: list[_Wait] = []
            if waiting.initial_days:
                waits.append(
                    _Wait(waiting.initial_days, "document", f"initial waiting {waiting.initial_days} days §4")
                )
            if waiting.specified_disease_months and diagnosis in specified:
                months = waiting.specified_disease_months
                waits.append(
                    _Wait(
                        _months_to_days(months, m.months_to_days),
                        "assumption",
                        f"specified disease waiting {months} months §4 (assumption A2)",
                    )
                )
            condition_wait: _Wait | None = None
            for ov in dc.overrides:
                if ov.product != product or ov.diagnosis not in (STAR, diagnosis):
                    continue
                status, section, basis, reason = ov.status, ov.section, ov.basis, ov.reason
                condition_wait = _condition_wait(ov, m.months_to_days)
            if condition_wait:
                waits.append(condition_wait)
            if diagnosis in exempt:
                waits = []
            top = max(waits, key=lambda w: w.days) if waits else None
            rows.append(
                CoverageGridRow(
                    product_name=product,
                    diagnosis=diagnosis,
                    coverage_status=status,
                    required_waiting_days=top.days if top else 0,
                    waiting_basis=top.basis if top else None,
                    waiting_reason=top.reason if top else None,
                    section_no=section,
                    coverage_basis=basis,
                    reason=reason,
                )
            )
    return rows


def _months_to_days(months: int, factor: float) -> int:
    return round(months * factor)


def _condition_wait(ov: CoverageOverride, factor: float) -> _Wait | None:
    section = ov.section or WAITING_SECTION
    if ov.condition_waiting_days:
        return _Wait(
            ov.condition_waiting_days,
            ov.basis,
            f"condition waiting {ov.condition_waiting_days} days §{section}",
        )
    if ov.condition_waiting_months:
        months = ov.condition_waiting_months
        return _Wait(
            _months_to_days(months, factor), ov.basis, f"condition waiting {months} months §{section}"
        )
    return None
