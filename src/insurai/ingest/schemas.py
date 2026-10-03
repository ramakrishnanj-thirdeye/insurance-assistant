"""Config and report models for the warehouse build (spec 01)."""

from datetime import date
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from insurai.knowledge.schemas import PolicyType


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DocCondition(_Strict):
    field_name: Literal["network_status", "diagnosis_or_loss_type"] = Field(alias="field")
    equals: str | None = None
    in_: list[str] | None = Field(default=None, alias="in")

    @model_validator(mode="after")
    def _exactly_one_operator(self) -> Self:
        if (self.equals is None) == (self.in_ is None):
            raise ValueError("a condition needs exactly one of 'equals' or 'in'")
        return self

    @property
    def values(self) -> list[str]:
        return [self.equals] if self.equals is not None else list(self.in_ or [])


class ConditionalDocs(_Strict):
    when: DocCondition
    add: list[str]


class PolicyTypeDocs(_Strict):
    always: list[str]
    conditional: list[ConditionalDocs]
    optional: list[str]
    untracked: list[str]
    source: str


class RequiredDocumentsConfig(_Strict):
    """Strict schema for config/required_documents.yaml."""

    version: int
    status: Literal["proposed", "approved"]
    document_types: list[str]
    policy_types: dict[PolicyType, PolicyTypeDocs]

    @model_validator(mode="after")
    def _documents_are_known_types(self) -> Self:
        known = set(self.document_types)
        for ptype, spec in self.policy_types.items():
            docs = [*spec.always, *spec.optional, *(d for c in spec.conditional for d in c.add)]
            unknown = [d for d in docs if d not in known]
            if unknown:
                raise ValueError(f"{ptype}: unknown document types {unknown}")
        return self


class RefTablesReport(BaseModel):
    required_documents_rows: int
    diagnosis_coverage_rows: int
    required_documents_status: str
    coverage_matrix_status: str


class IntegrityCheck(BaseModel):
    name: str
    description: str
    passed: bool
    failing_rows: int


class AnomalyMetric(BaseModel):
    name: str
    description: str
    value: int | float | dict[str, float]


class DataQualityReport(BaseModel):
    as_of: date
    integrity_checks: list[IntegrityCheck]
    anomaly_metrics: list[AnomalyMetric]
    row_counts: dict[str, int] = Field(default_factory=dict)
    gold_checksums: dict[str, str] = Field(default_factory=dict)

    @property
    def integrity_passed(self) -> bool:
        return all(c.passed for c in self.integrity_checks)

    def metric(self, name: str) -> AnomalyMetric:
        return next(m for m in self.anomaly_metrics if m.name == name)


class WarehouseReport(BaseModel):
    warehouse_path: Path
    dq_report_path: Path
    build_seconds: float
    ref: RefTablesReport
    data_quality: DataQualityReport
