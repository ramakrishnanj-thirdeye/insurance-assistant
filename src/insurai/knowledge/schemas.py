"""Policy knowledge models (spec 03): wording sections, retrieval chunks, coverage matrix and cells."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from insurai.tools.schemas import SourceRef

PolicyType = Literal["Health", "Motor", "Travel"]
CoverageStatus = Literal["covered", "conditional", "not_covered", "not_applicable", "needs_review"]
Basis = Literal["document", "assumption"]
CoverageAttribute = Literal["sum_insured", "waiting_period", "maternity", "exclusions", "claim_procedure"]

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


class PolicySection(BaseModel):
    """One numbered section of a policy wording."""

    model_config = ConfigDict(frozen=True)

    product: str
    policy_type: PolicyType
    section_no: int
    section_name: str
    text: str
    content_hash: str
    source_path: str


class PolicyChunk(BaseModel):
    """A retrieval unit: one product section, one common section (product "ALL") or one FAQ pair."""

    model_config = ConfigDict(frozen=True)

    chunk_id: str  # "health-secure-plus-s5", "all-s13", "all-s15-q2"
    product: str  # canonical product name or "ALL"
    policy_type: str | None  # None for ALL
    section_no: int
    section_name: str
    is_common: bool
    text: str  # clause text only
    header: str  # "Health Secure Plus (Health) › §5 Maternity"
    embed_text: str  # f"{header}: {text}", what gets embedded
    citation_label: str  # "[Health Secure Plus §5 Maternity]" / "[All products §13 Human Review]"
    content_hash: str
    source_path: str


class CoverageCell(BaseModel):
    """One product × attribute answer from the coverage matrix, cited to its wording section."""

    model_config = ConfigDict(frozen=True)

    product: str
    policy_type: PolicyType
    attribute: CoverageAttribute
    section_no: int
    section_name: str
    status: CoverageStatus | None = None  # maternity only
    waiting_months: int | None = None  # maternity waiting
    waiting_days: int | None = None  # waiting_period: initial waiting days
    specified_disease_months: int | None = None  # waiting_period
    pre_existing_months: int | None = None  # waiting_period
    amounts_inr: list[int] | None = None  # sum_insured options
    items: list[str] | None = None  # exclusions
    text: str  # the clause as worded
    sources: list[SourceRef]
