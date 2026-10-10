"""Agent graph models (spec 06 State, Synthesis contract, Trace)."""

from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic.json_schema import SkipJsonSchema

from insurai.tools.schemas import SourceRef


class Entities(BaseModel):
    claim_id: str | None = None
    policy_id: str | None = None
    customer_id: str | None = None
    hospital_id: str | None = None
    product: str | None = None
    policy_type: str | None = None
    hospital_name: str | None = None
    city: str | None = None

    def merged(self, other: "Entities") -> "Entities":
        """Self with every field `other` sets replacing it (a new ID replaces the active one)."""
        return self.model_copy(update=other.model_dump(exclude_none=True))

    def set_fields(self) -> dict[str, str]:
        return self.model_dump(exclude_none=True)


IntentType = Literal[
    "claim_status",
    "claim_documents",
    "claim_interactions",
    "claim_analysis",
    "policy_details",
    "policy_question",
    "coverage_compare",
    "hospital_check",
    "customer_summary",
    "analytics",
    "greeting",
    "out_of_scope",
]
NO_WORKER: frozenset[str] = frozenset({"greeting", "out_of_scope"})


class Intent(BaseModel):
    id: str
    type: IntentType
    entities: Entities = Field(default_factory=Entities)
    sub_question: str
    # Set by finalize_plan, never by the planner (hidden from its schema). claim_analysis only: "assess"
    # may pause for human review, "explain" never does (spec 06); `question` is the user's message, which
    # the dossier checks for a false premise (spec 07).
    mode: SkipJsonSchema[Literal["assess", "explain"] | None] = None
    question: SkipJsonSchema[str | None] = None
    # policy_question on a guarantee turn: sections fetched by chunk id next to the search (spec 08).
    pinned_sections: SkipJsonSchema[list[int] | None] = None
    # policy_question routed by rule 2 to the common sections: the search keeps only common (ALL) chunks.
    common_only: SkipJsonSchema[bool] = False
    # Added by the guarantee augmentation (spec 08), not asked for by the user.
    added_by: SkipJsonSchema[Literal["guarantee"] | None] = None
    # claim_analysis only: False on a guarantee-only turn, answered without a narrative (AC-08-24).
    narrate: SkipJsonSchema[bool] = True


class Plan(BaseModel):
    intents: list[Intent] = Field(default_factory=list)
    clarification: str | None = None  # set → ask the user instead of running workers


ALL_ROWS = "all_rows"  # analytics evidence payload key with every row: UI table and V3, never the prompt


class Evidence(BaseModel):
    intent_id: str
    worker: str
    kind: str  # result model name, "not_found", "access_denied", "disambiguation", "unavailable"
    payload: dict[str, Any]
    sources: list[SourceRef]
    summary: str


class AnswerDraft(BaseModel):
    answer_markdown: str  # every factual sentence ends with ≥ 1 citation label from evidence
    citations: list[str] = Field(default_factory=list)  # labels parsed from answer_markdown (regex)
    # Model-written text (generator or dossier narrative), not a deterministic template: V7 judges only these.
    llm_written: SkipJsonSchema[bool] = False


class Reset(BaseModel):
    kind: Literal["reset"] = "reset"


TraceKind = Literal[
    "intent", "entity", "node", "tool", "retrieval", "rule", "verify", "prompt", "llm", "warning", "total"
]


class TraceEvent(BaseModel):
    kind: TraceKind
    name: str
    turn: int
    start_ms: float  # epoch milliseconds; spans from parallel workers overlap
    end_ms: float
    data: dict[str, Any] = Field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        return round(self.end_ms - self.start_ms, 1)


class AnalyticsPayload(BaseModel):
    """The analytics result of a turn, for the UI table and chart (spec 02, spec 10)."""

    sql: str
    columns: list[str]
    rows: list[list[Any]]  # at most sql.row_limit
    row_count: int
    truncated: bool
    chart: dict[str, Any] | None = None  # ChartSpec: {type: bar|line, x, y}


class TurnResult(BaseModel):
    thread_id: str
    answer_markdown: str
    citations: list[str]
    trace: list[TraceEvent]
    interrupt: dict[str, Any] | None = None  # assessment summary when the dossier waits for review
    assessment: dict[str, Any] | None = None
    verification_passed: bool | None = None
    analytics: AnalyticsPayload | None = None
