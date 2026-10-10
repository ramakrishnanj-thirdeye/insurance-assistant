"""Request and response models (spec 09 Endpoints). OpenAPI at /docs is generated from these."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from insurai.agent.schemas import Entities, TraceEvent
from insurai.agent.threads import ThreadRecord, ThreadSource, ThreadStatus
from insurai.tools.schemas import Persona


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: str | None = None  # omitted: the server creates a thread
    persona: Persona | None = None  # optional; must equal X-Persona when given
    principal_id: str | None = None  # optional; must equal X-Principal-Id when given
    source: ThreadSource = "api"


class ResumeRequest(BaseModel):
    thread_id: str
    action: Literal["approve", "override", "request_info"]
    note: str = Field(default="", max_length=2000)


class RenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ThreadSummary(BaseModel):
    thread_id: str
    title: str
    status: ThreadStatus
    source: ThreadSource
    turn_count: int
    last_entities: Entities | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, record: ThreadRecord) -> "ThreadSummary":
        return cls.model_validate(record.model_dump(include=set(cls.model_fields)))


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ThreadDetail(ThreadSummary):
    messages: list[ChatMessage]
    last_trace: list[TraceEvent]
    pending_review: dict[str, Any] | None


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    warehouse: str  # "ok" or "error: <reason>"
    qdrant: str
    llm_profile: str
    as_of: date
    coverage_status: str
    versions: dict[str, Any]


class EvalReportSummary(BaseModel):
    run_id: str
    suite: str
    created_at: str | None
    git_sha: str | None
    baseline_of: str | None = None  # set on the baseline: the run it was promoted from
    headline: dict[str, dict[str, float | int]]  # slice or config -> scalar metrics
