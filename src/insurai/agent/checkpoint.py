"""Checkpointers (spec 06 Memory): InMemorySaver for tests and in-process evals, SqliteSaver for sync
scripts, AsyncSqliteSaver for the async API (spec 09). All share `paths.checkpoints`.
"""

import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from insurai.agent import schemas as agent_schemas
from insurai.guardrails import schemas as guard_schemas
from insurai.rules import schemas as rules_schemas
from insurai.settings import get_settings

# State values the checkpointer may rebuild; anything else is refused (strict msgpack allowlist).
STATE_TYPES: tuple[type, ...] = (
    agent_schemas.Entities,
    agent_schemas.Intent,
    agent_schemas.Plan,
    agent_schemas.Evidence,
    agent_schemas.AnswerDraft,
    agent_schemas.TraceEvent,
    agent_schemas.Reset,
    guard_schemas.GuardResult,
    guard_schemas.CheckOutcome,
    guard_schemas.VerificationReport,
    rules_schemas.ClaimAssessment,
    rules_schemas.RuleResult,
    rules_schemas.ConsistencyFlag,
    rules_schemas.ReviewDecision,
)


def serde() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=None).with_msgpack_allowlist(STATE_TYPES)


def memory_saver() -> InMemorySaver:
    return InMemorySaver(serde=serde())


def sqlite_saver(path: Path | None = None) -> SqliteSaver:
    path = path or get_settings().paths.checkpoints
    path.parent.mkdir(parents=True, exist_ok=True)
    saver = SqliteSaver(sqlite3.connect(str(path), check_same_thread=False), serde=serde())
    saver.setup()
    return saver


@asynccontextmanager
async def async_sqlite_saver(path: Path | None = None) -> AsyncIterator[AsyncSqliteSaver]:
    path = path or get_settings().paths.checkpoints
    path.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
        saver.serde = serde()
        yield saver
