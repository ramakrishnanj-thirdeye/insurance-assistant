"""Semantic layer models (spec 02): the semantic model in the Cortex Analyst shape, and the text-to-SQL
pipeline's drafts, validated statements, rejections, results and chart specs."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class VerifiedQuery(BaseModel):
    """A tested question → SQL pair; seeds the sql_examples collection (spec 04)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    question: str
    sql: str


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BaseTable(_Frozen):
    database: str
    schema_: str = Field(alias="schema")
    table: str

    @property
    def qualified(self) -> str:
        return f"{self.schema_}.{self.table}"


class PrimaryKey(_Frozen):
    columns: list[str]


class Column(_Frozen):
    """A dimension, time dimension or fact."""

    name: str
    expr: str
    data_type: str
    description: str | None = None
    synonyms: list[str] = Field(default_factory=list)
    sample_values: list[Any] = Field(default_factory=list)
    is_enum: bool = False
    unique: bool = False
    pii: bool = False


class NamedExpr(_Frozen):
    """A metric or a named filter."""

    name: str
    expr: str
    description: str | None = None
    synonyms: list[str] = Field(default_factory=list)


class TableModel(_Frozen):
    name: str
    description: str
    base_table: BaseTable
    primary_key: PrimaryKey | None = None
    dimensions: list[Column] = Field(default_factory=list)
    time_dimensions: list[Column] = Field(default_factory=list)
    facts: list[Column] = Field(default_factory=list)
    metrics: list[NamedExpr] = Field(default_factory=list)
    filters: list[NamedExpr] = Field(default_factory=list)
    blocked_columns: list[str] = Field(default_factory=list)  # never selectable or joinable

    @property
    def columns(self) -> list[Column]:
        return [*self.dimensions, *self.time_dimensions, *self.facts]


class JoinColumns(_Frozen):
    left_column: str
    right_column: str


class Relationship(_Frozen):
    name: str
    left_table: str
    right_table: str
    join_type: Literal["inner", "left_outer"]
    relationship_type: Literal["many_to_one", "one_to_one"]
    relationship_columns: list[JoinColumns] = Field(min_length=1)


# --- text-to-SQL pipeline -------------------------------------------------------------------------------


class SqlDraft(BaseModel):
    sql: str
    rationale: str


class ValidatedSql(BaseModel):
    sql: str  # what runs: LIMIT applied, masking applied
    tables: list[str]  # "schema.table", in order of first reference
    limit_applied: int
    limit_imposed: bool = False  # the LIMIT is ours (injected or capped), so a full page may be truncated


RejectionReason = Literal[
    "parse",
    "not_select",
    "multi_statement",
    "forbidden_function",
    "unknown_table",
    "unknown_column",
    "forbidden_join",
    "hidden_column",
    "persona",
    "timeout",
    "runtime",
]


class SqlRejection(BaseModel):
    reason: RejectionReason
    detail: str


class QueryResult(BaseModel):
    columns: list[str]
    rows: list[list[Any]]  # JSON-safe values: Decimal → float, dates → ISO strings
    row_count: int
    truncated: bool
    column_kinds: list[Literal["numeric", "temporal", "text", "other"]] = Field(default_factory=list)


class ChartSpec(BaseModel):
    type: Literal["bar", "line"]
    x: str
    y: str
