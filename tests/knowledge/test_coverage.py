import pytest

from insurai.knowledge.coverage import coverage_grid, load_coverage
from insurai.knowledge.schemas import CoverageGridRow, CoverageMatrix
from insurai.settings import ROOT

pytestmark = pytest.mark.unit

COVERAGE_FILE = ROOT / "config" / "coverage_matrix.yaml"


@pytest.fixture(scope="module")
def grid() -> dict[tuple[str, str], CoverageGridRow]:
    rows = coverage_grid(load_coverage(COVERAGE_FILE))
    return {(r.product_name, r.diagnosis): r for r in rows}


def test_AC_01_05_grid_has_85_rows_32_with_waits(grid: dict[tuple[str, str], CoverageGridRow]) -> None:
    assert len(grid) == 85
    assert sum(1 for r in grid.values() if r.required_waiting_days > 0) == 32


@pytest.mark.parametrize(
    ("product", "diagnosis", "status", "days", "basis"),
    [
        ("Critical Care Elite", "Maternity", "not_covered", 0, None),
        ("Senior Health Shield", "Maternity", "not_applicable", 30, "document"),
        ("Family Care Gold", "Maternity", "conditional", 730, "document"),
        ("Critical Care Elite", "Cardiac Procedure", "covered", 90, "assumption"),
        ("Health Secure Plus", "Cataract", "covered", 730, "assumption"),
    ],
)
def test_AC_01_05_named_cells(
    grid: dict[tuple[str, str], CoverageGridRow],
    product: str,
    diagnosis: str,
    status: str,
    days: int,
    basis: str | None,
) -> None:
    row = grid[(product, diagnosis)]
    assert row.coverage_status == status
    assert row.required_waiting_days == days
    assert row.waiting_basis == basis


def test_AC_01_05_accidental_injury_has_no_wait_anywhere(
    grid: dict[tuple[str, str], CoverageGridRow],
) -> None:
    accidental = [r for (_, diagnosis), r in grid.items() if diagnosis == "Accidental Injury"]
    assert len(accidental) == 5
    assert all(r.required_waiting_days == 0 and r.waiting_basis is None for r in accidental)


def test_AC_01_05_specific_override_does_not_inherit_star_reason(
    grid: dict[tuple[str, str], CoverageGridRow],
) -> None:
    # The "*" override's "wording lists none" reason must not leak onto a specific override listed after it.
    maternity = grid[("Critical Care Elite", "Maternity")]
    assert (maternity.coverage_status, maternity.section_no) == ("not_covered", 5)
    assert maternity.reason is None
    assert grid[("Critical Care Elite", "Cardiac Procedure")].reason is None
    # Diagnoses covered only by "*" keep its reason.
    assert "lists none" in (grid[("Critical Care Elite", "Viral Fever")].reason or "")


def test_AC_01_05_every_product_gets_every_diagnosis_of_its_type(
    grid: dict[tuple[str, str], CoverageGridRow],
) -> None:
    matrix = load_coverage(COVERAGE_FILE)
    for product, spec in matrix.products.items():
        expected = set(matrix.diagnosis_coverage.diagnoses[spec.policy_type])
        assert {d for (p, d) in grid if p == product} == expected


def _matrix(overrides: list[dict], exempt: list[str] | None = None) -> CoverageMatrix:
    return CoverageMatrix.model_validate(
        {
            "version": 1,
            "status": "draft",
            "months_to_days": 30.4167,
            "products": {
                "P": {
                    "policy_type": "Health",
                    "file": "P.txt",
                    "sum_insured_options_inr": [100000],
                    "waiting": {"initial_days": 30, "specified_disease_months": 24, "text": "t"},
                    "maternity": {"status": "covered", "waiting_months": None, "text": "t"},
                    "exclusions": [],
                    "claim_procedure": "t",
                }
            },
            "common_terms": {"sections": [1], "obligations": {}},
            "diagnosis_coverage": {
                "statuses": ["covered", "conditional", "not_covered", "not_applicable", "needs_review"],
                "diagnoses": {"Health": ["Flu", "Cataract", "Fracture"], "Motor": [], "Travel": []},
                "default_status": "covered",
                "assumptions": {
                    "A1_accident_exempt": {"diagnoses": exempt or ["Fracture"], "note": "n"},
                    "A2_specified_diseases": {"diagnoses": ["Cataract"], "note": "n"},
                    "A3_critical_illnesses": {"diagnoses": [], "note": "n"},
                },
                "overrides": overrides,
            },
        }
    )


def test_AC_01_05_specific_override_beats_star() -> None:
    rows = coverage_grid(
        _matrix(
            [
                {"product": "P", "diagnosis": "*", "status": "needs_review", "section": 4, "reason": "star"},
                {
                    "product": "P",
                    "diagnosis": "Flu",
                    "status": "covered",
                    "section": 5,
                    "basis": "assumption",
                },
            ]
        )
    )
    by_diag = {r.diagnosis: r for r in rows}
    assert by_diag["Flu"].coverage_status == "covered"
    assert by_diag["Flu"].section_no == 5
    assert by_diag["Flu"].coverage_basis == "assumption"
    assert by_diag["Flu"].reason is None
    assert by_diag["Cataract"].coverage_status == "needs_review"
    assert by_diag["Cataract"].reason == "star"


def test_AC_01_05_largest_wait_wins_and_carries_its_basis() -> None:
    rows = coverage_grid(
        _matrix([{"product": "P", "diagnosis": "Flu", "status": "covered", "condition_waiting_days": 90}])
    )
    by_diag = {r.diagnosis: r for r in rows}
    assert (by_diag["Flu"].required_waiting_days, by_diag["Flu"].waiting_basis) == (90, "document")
    assert (by_diag["Cataract"].required_waiting_days, by_diag["Cataract"].waiting_basis) == (
        730,
        "assumption",
    )
    assert (
        by_diag["Cataract"].waiting_reason is not None and "24 months" in by_diag["Cataract"].waiting_reason
    )


def test_AC_01_05_accident_exempt_has_no_wait() -> None:
    rows = coverage_grid(
        _matrix(
            [{"product": "P", "diagnosis": "Fracture", "status": "covered", "condition_waiting_days": 90}]
        )
    )
    fracture = next(r for r in rows if r.diagnosis == "Fracture")
    assert fracture.required_waiting_days == 0
    assert fracture.waiting_basis is None and fracture.waiting_reason is None


def test_AC_01_05_override_for_unknown_product_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown product"):
        _matrix([{"product": "Nope", "diagnosis": "*", "status": "covered"}])


def test_AC_01_05_override_for_diagnosis_outside_policy_type_is_rejected() -> None:
    with pytest.raises(ValueError, match="not a Health diagnosis"):
        _matrix([{"product": "P", "diagnosis": "Theft", "status": "covered"}])
