"""Policy knowledge models (spec 03). Only the coverage matrix is implemented so far (spec 01 needs it)."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

PolicyType = Literal["Health", "Motor", "Travel"]
CoverageStatus = Literal["covered", "conditional", "not_covered", "not_applicable", "needs_review"]
Basis = Literal["document", "assumption"]

STAR = "*"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Waiting(_Strict):
    initial_days: int | None = None
    specified_disease_months: int | None = None
    pre_existing_months: int | None = None
    condition_days: dict[str, int] | None = None
    condition_months: dict[str, int] | None = None
    accident_exempt: bool = False
    text: str


class Maternity(_Strict):
    status: CoverageStatus
    waiting_months: int | None
    text: str


class Product(_Strict):
    policy_type: PolicyType
    file: str
    sum_insured_options_inr: list[int] | None
    sum_insured_text: str | None = None
    waiting: Waiting
    maternity: Maternity
    exclusions: list[str]
    claim_procedure: str


class CommonTerms(_Strict):
    sections: list[int]
    obligations: dict[str, str]


class Assumption(_Strict):
    diagnoses: list[str]
    note: str


class CoverageOverride(_Strict):
    product: str
    diagnosis: str  # a diagnosis of the product's policy type, or "*" for all of them
    status: CoverageStatus
    section: int | None = None
    basis: Basis = "document"
    reason: str | None = None
    condition_waiting_days: int | None = None
    condition_waiting_months: int | None = None


class DiagnosisCoverage(_Strict):
    statuses: list[CoverageStatus]
    diagnoses: dict[PolicyType, list[str]]
    default_status: CoverageStatus
    assumptions: dict[str, Assumption]
    overrides: list[CoverageOverride]

    def assumption(self, key: str) -> set[str]:
        return set(self.assumptions[key].diagnoses) if key in self.assumptions else set()


class CoverageMatrix(_Strict):
    """Strict schema for config/coverage_matrix.yaml."""

    version: int
    status: Literal["draft", "reviewed"]
    months_to_days: float
    products: dict[str, Product]
    common_terms: CommonTerms
    diagnosis_coverage: DiagnosisCoverage

    @model_validator(mode="after")
    def _overrides_reference_known_cells(self) -> Self:
        for ov in self.diagnosis_coverage.overrides:
            if ov.product not in self.products:
                raise ValueError(f"override for unknown product {ov.product!r}")
            policy_type = self.products[ov.product].policy_type
            if ov.diagnosis != STAR and ov.diagnosis not in self.diagnosis_coverage.diagnoses[policy_type]:
                raise ValueError(f"override diagnosis {ov.diagnosis!r} is not a {policy_type} diagnosis")
        return self


class CoverageGridRow(BaseModel):
    """One row of ref.diagnosis_coverage: a product × diagnosis cell."""

    model_config = ConfigDict(frozen=True)

    product_name: str
    diagnosis: str
    coverage_status: CoverageStatus
    required_waiting_days: int
    waiting_basis: Basis | None
    waiting_reason: str | None
    section_no: int | None
    coverage_basis: Basis
    reason: str | None
