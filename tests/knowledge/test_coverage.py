import csv
import re

import pytest

from insurai.formatting import inr
from insurai.knowledge.coverage import coverage_grid, get_coverage, load_coverage
from insurai.knowledge.parse import build_chunks, parse_corpus, parse_policy_file
from insurai.knowledge.schemas import CoverageGridRow, CoverageMatrix
from insurai.settings import ROOT, get_settings

pytestmark = pytest.mark.unit

COVERAGE_FILE = ROOT / "config" / "coverage_matrix.yaml"
SUM_INSURED_PREFIX = "Available coverage limits: "


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


# --- spec 03 -----------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def wording() -> dict[str, dict[int, str]]:
    """Section texts per product, whitespace-collapsed, straight from the policy files."""
    out: dict[str, dict[int, str]] = {}
    for s in parse_corpus(get_settings().paths.policy_docs_dir):
        out.setdefault(s.product, {})[s.section_no] = " ".join(s.text.split())
    return out


def test_AC_03_05_matrix_validates_and_covers_every_policies_csv_product() -> None:
    matrix = load_coverage(COVERAGE_FILE)
    with (ROOT / "data" / "raw" / "policies.csv").open(encoding="utf-8", newline="") as f:
        csv_products = {(row["product_name"], row["policy_type"]) for row in csv.DictReader(f)}
    assert {(p, spec.policy_type) for p, spec in matrix.products.items()} == csv_products


def test_AC_03_05_product_file_and_type_match_wording() -> None:
    matrix = load_coverage(COVERAGE_FILE)
    docs = get_settings().paths.policy_docs_dir
    for product, spec in matrix.products.items():
        sections = parse_policy_file(docs / spec.file)
        assert sections[0].product == product
        assert sections[0].policy_type == spec.policy_type


def _sentence_case(item: str) -> str:
    return item[:1].upper() + item[1:]


def test_AC_03_05_exclusions_match_section_9_split_on_commas(wording: dict[str, dict[int, str]]) -> None:
    matrix = load_coverage(COVERAGE_FILE)
    for product, spec in matrix.products.items():
        parts = [p.strip() for p in wording[product][9].rstrip(".").split(",")]
        assert spec.exclusions == [_sentence_case(p) for p in parts], product


def test_AC_03_06_support_matrix_texts_quote_the_wordings(wording: dict[str, dict[int, str]]) -> None:
    """Mechanical aid for the manual review (AC-03-06 itself stays a human gate)."""
    matrix = load_coverage(COVERAGE_FILE)
    for product, spec in matrix.products.items():
        sec = wording[product]
        assert spec.waiting.text == sec[4], product
        assert spec.maternity.text == sec[5], product
        assert spec.claim_procedure == sec[10], product
        amounts = [int(a.replace(",", "")) for a in re.findall(r"₹([\d,]+)", sec[2])]
        assert (spec.sum_insured_options_inr or []) == amounts, product
        limits = sec[2].removeprefix(SUM_INSURED_PREFIX)
        if spec.sum_insured_text is not None:
            assert spec.sum_insured_text == limits, product
        else:
            # Without a text, the amounts alone must say everything §2 says.
            assert " / ".join(inr(a) for a in amounts) + "." == limits, product


def test_AC_03_09_sum_insured_text_comes_back_from_get_coverage(wording: dict[str, dict[int, str]]) -> None:
    for cell in get_coverage(None, "sum_insured"):
        assert cell.text.rstrip(".") == wording[cell.product][2].removeprefix(SUM_INSURED_PREFIX).rstrip(".")
    travel = get_coverage("Global Travel Secure", "sum_insured")[0]
    assert travel.text == "₹5,00,000 / ₹10,00,000 equivalent limits."
    assert travel.amounts_inr == [500000, 1000000]


def test_AC_03_07_coverage_grid_is_the_shared_function() -> None:
    from insurai.ingest import ref_tables

    assert ref_tables.coverage_grid is coverage_grid


def test_AC_03_09_health_secure_plus_maternity() -> None:
    cells = get_coverage("Health Secure Plus", "maternity")
    assert len(cells) == 1
    cell = cells[0]
    assert cell.status == "covered"
    assert cell.waiting_months == 24
    assert cell.section_no == 5
    assert [s.label for s in cell.sources] == ["[Health Secure Plus §5 Maternity]"]
    src = cell.sources[0]
    assert (src.kind, src.product, src.section_no, src.section_name) == (
        "policy",
        "Health Secure Plus",
        5,
        "Maternity",
    )


def test_AC_03_09_product_match_is_case_insensitive() -> None:
    assert get_coverage("health secure plus", "maternity") == get_coverage("Health Secure Plus", "maternity")


def test_AC_03_09_unknown_product_or_attribute_raises() -> None:
    with pytest.raises(ValueError, match="Unknown product"):
        get_coverage("Pet Plan", "maternity")
    with pytest.raises(ValueError, match="Unknown attribute"):
        get_coverage("Health Secure Plus", "dental")


def test_AC_03_09_no_args_returns_every_cell_with_labels_from_the_wordings() -> None:
    cells = get_coverage(None, None)
    assert len(cells) == 50
    chunk_labels = {
        c.citation_label for c in build_chunks(parse_corpus(get_settings().paths.policy_docs_dir))
    }
    assert all(len(c.sources) == 1 and c.sources[0].label in chunk_labels for c in cells)


def test_AC_03_09_attribute_values() -> None:
    exclusions = get_coverage("Two Wheeler Secure", "exclusions")[0]
    assert "Drunk driving" in exclusions.items
    assert exclusions.sources[0].label == "[Two Wheeler Secure §9 Exclusions]"
    si = get_coverage("Health Secure Plus", "sum_insured")[0]
    assert si.amounts_inr == [500000, 1000000, 2000000]
    waiting = get_coverage("Family Care Gold", "waiting_period")[0]
    assert (waiting.waiting_days, waiting.specified_disease_months, waiting.pre_existing_months) == (
        30,
        24,
        48,
    )
    assert get_coverage("Critical Care Elite", "maternity")[0].status == "not_covered"
    comparison = get_coverage(None, "maternity")
    assert len(comparison) == 10
