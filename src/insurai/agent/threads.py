"""Thread store (spec 09 Thread management, ADR-009): ownership, status machine and busy lease.

The `threads` table lives in the same SQLite file as the LangGraph checkpointer (`paths.checkpoints`) on
its own aiosqlite connection. Timestamps are wall-clock UTC metadata, not business dates.

The busy check is a lease: `start_run` marks a thread running with a token under a per-thread
`asyncio.Lock`; a lease older than `agent.turn_timeout_s` is stale and the next request takes it over.
The lock is in-process, so this assumes a single API worker (production: a database or Redis lock).

python -m insurai.agent.threads --reset      # delete paths.checkpoints (stop make api first)
"""

import argparse
import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Collection
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import aiosqlite
from langgraph.checkpoint.base import BaseCheckpointSaver
from pydantic import BaseModel

from insurai.agent.schemas import Entities
from insurai.guardrails.pii import mask
from insurai.observability import get_logger
from insurai.settings import get_settings
from insurai.tools.schemas import Persona

log = get_logger(__name__)

ThreadStatus = Literal["active", "running", "awaiting_review"]
ThreadSource = Literal["ui", "api", "eval", "demo"]
TITLE_MAX = 60
ELLIPSIS = "…"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
    thread_id     TEXT PRIMARY KEY,
    persona       TEXT NOT NULL,
    principal_id  TEXT NOT NULL,
    title         TEXT NOT NULL,
    status        TEXT NOT NULL,
    source        TEXT NOT NULL,
    turn_count    INTEGER NOT NULL DEFAULT 0,
    last_entities TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    running_since TEXT,
    run_token     TEXT
);
CREATE INDEX IF NOT EXISTS threads_owner ON threads (persona, principal_id, updated_at);
"""
_COLUMNS = (
    "thread_id, persona, principal_id, title, status, source, turn_count, last_entities, "
    "created_at, updated_at, running_since, run_token"
)


class ThreadRecord(BaseModel):
    thread_id: str  # uuid4 hex, created server-side only
    persona: Persona
    principal_id: str
    title: str  # first user message, PII-masked, <= 60 chars + "…"
    status: ThreadStatus
    source: ThreadSource
    turn_count: int
    last_entities: Entities | None
    created_at: datetime
    updated_at: datetime
    running_since: datetime | None = None  # start of the current lease while status is running


class ThreadNotFound(LookupError):
    """Unknown thread ID (404 THREAD_NOT_FOUND)."""


class ThreadForbidden(PermissionError):
    """The thread belongs to another persona or principal (403 THREAD_FORBIDDEN)."""


class ThreadBusy(RuntimeError):
    """The thread holds a fresh running lease (409 THREAD_BUSY)."""


class ThreadStateChanged(RuntimeError):
    """The thread is not in a status this run may start from (the caller maps it to its 409)."""

    def __init__(self, thread_id: str, status: ThreadStatus) -> None:
        super().__init__(f"thread {thread_id} is {status}")
        self.status = status


def utcnow() -> datetime:
    return datetime.now(UTC)  # wall-clock metadata (spec 09), never a business date


def make_title(first_message: str) -> str:
    masked, _ = mask(" ".join(first_message.split()))
    return masked if len(masked) <= TITLE_MAX else masked[:TITLE_MAX].rstrip() + ELLIPSIS


class ThreadStore:
    def __init__(
        self,
        conn: aiosqlite.Connection,
        checkpointer: BaseCheckpointSaver | None = None,
        has_pending_review: Callable[[str], Awaitable[bool]] | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._conn = conn
        self._checkpointer = checkpointer
        self._has_pending_review = has_pending_review
        self._clock = clock
        self._locks: dict[str, asyncio.Lock] = {}

    @classmethod
    @asynccontextmanager
    async def open(
        cls,
        path: Path | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
        has_pending_review: Callable[[str], Awaitable[bool]] | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> AsyncIterator["ThreadStore"]:
        path = path or get_settings().paths.checkpoints
        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(str(path)) as conn:
            await conn.execute("PRAGMA busy_timeout = 5000")
            await conn.executescript(_SCHEMA)
            await conn.commit()
            yield cls(conn, checkpointer, has_pending_review, clock)

    # --- spec 09 interface --------------------------------------------------------------------------------

    async def create(
        self, persona: Persona, principal_id: str, first_message: str, source: ThreadSource
    ) -> ThreadRecord:
        now = self._clock()
        record = ThreadRecord(
            thread_id=uuid.uuid4().hex,
            persona=persona,
            principal_id=principal_id,
            title=make_title(first_message),
            status="active",
            source=source,
            turn_count=0,
            last_entities=None,
            created_at=now,
            updated_at=now,
        )
        await self._conn.execute(
            f"INSERT INTO threads ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, 0, NULL, ?, ?, NULL, NULL)",
            (
                record.thread_id,
                persona,
                principal_id,
                record.title,
                "active",
                source,
                now.isoformat(),
                now.isoformat(),
            ),
        )
        await self._conn.commit()
        return record

    async def authorize(self, thread_id: str, persona: Persona, principal_id: str) -> ThreadRecord:
        record = await self.get(thread_id)
        if record.persona != persona or record.principal_id != principal_id:
            raise ThreadForbidden(thread_id)
        return record

    async def list(
        self, persona: Persona, principal_id: str, limit: int = 20, offset: int = 0
    ) -> list[ThreadRecord]:
        async with self._conn.execute(
            f"SELECT {_COLUMNS} FROM threads WHERE persona = ? AND principal_id = ? "
            "ORDER BY updated_at DESC, created_at DESC, rowid DESC LIMIT ? OFFSET ?",
            (persona, principal_id, limit, offset),
        ) as cur:
            return [_record(row) for row in await cur.fetchall()]

    async def set_status(self, thread_id: str, status: ThreadStatus) -> None:
        running_since = self._clock().isoformat() if status == "running" else None
        await self._conn.execute(
            "UPDATE threads SET status = ?, running_since = ?, run_token = NULL WHERE thread_id = ?",
            (status, running_since, thread_id),
        )
        await self._conn.commit()

    async def touch(self, thread_id: str, entities: Entities | None) -> None:
        await self._conn.execute(
            "UPDATE threads SET turn_count = turn_count + 1, updated_at = ?, last_entities = ? "
            "WHERE thread_id = ?",
            (self._clock().isoformat(), _entities_json(entities), thread_id),
        )
        await self._conn.commit()

    async def rename(self, thread_id: str, title: str) -> None:
        await self._conn.execute(
            "UPDATE threads SET title = ?, updated_at = ? WHERE thread_id = ?",
            (make_title(title), self._clock().isoformat(), thread_id),
        )
        await self._conn.commit()

    async def delete(self, thread_id: str) -> None:
        await self._conn.execute("DELETE FROM threads WHERE thread_id = ?", (thread_id,))
        await self._conn.commit()
        self._locks.pop(thread_id, None)
        if self._checkpointer is not None:
            await self._checkpointer.adelete_thread(thread_id)

    async def recover(self) -> int:
        """At startup: running threads go to awaiting_review if their checkpoint waits for a review,
        otherwise to active. Returns how many threads were reset."""
        async with self._conn.execute("SELECT thread_id FROM threads WHERE status = 'running'") as cur:
            stale = [row[0] for row in await cur.fetchall()]
        for thread_id in stale:
            pending = self._has_pending_review is not None and await self._has_pending_review(thread_id)
            await self.set_status(thread_id, "awaiting_review" if pending else "active")
            log.info(
                "recovered thread %s: running -> %s", thread_id, "awaiting_review" if pending else "active"
            )
        return len(stale)

    # --- lease --------------------------------------------------------------------------------------------

    async def get(self, thread_id: str) -> ThreadRecord:
        async with self._conn.execute(
            f"SELECT {_COLUMNS} FROM threads WHERE thread_id = ?", (thread_id,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            raise ThreadNotFound(thread_id)
        return _record(row)

    async def start_run(
        self, thread_id: str, allowed: Collection[ThreadStatus], timeout_s: float | None = None
    ) -> str:
        """Take the running lease and return its token.

        ThreadBusy while another run holds a fresh lease; a lease older than `timeout_s` is taken over and
        logged. ThreadStateChanged when the thread is in none of the `allowed` statuses.
        """
        timeout_s = get_settings().agent.turn_timeout_s if timeout_s is None else timeout_s
        async with self._lock(thread_id):
            record = await self.get(thread_id)
            now = self._clock()
            if record.status == "running":
                age = (now - record.running_since).total_seconds() if record.running_since else None
                if age is not None and age < timeout_s:
                    raise ThreadBusy(thread_id)
                log.warning(
                    "thread %s: taking over a stale running lease (age %s s, turn_timeout_s %s)",
                    thread_id,
                    "unknown" if age is None else round(age, 1),
                    timeout_s,
                )
            elif record.status not in allowed:
                raise ThreadStateChanged(thread_id, record.status)
            token = uuid.uuid4().hex
            await self._conn.execute(
                "UPDATE threads SET status = 'running', running_since = ?, run_token = ? WHERE thread_id = ?",
                (now.isoformat(), token, thread_id),
            )
            await self._conn.commit()
            return token

    async def finish_run(
        self,
        thread_id: str,
        token: str,
        status: ThreadStatus,
        entities: Entities | None = None,
        count_turn: bool = False,
    ) -> bool:
        """End the lease if `token` still holds it; False (and no change) after a takeover or delete."""
        async with self._lock(thread_id):
            async with self._conn.execute(
                "SELECT run_token FROM threads WHERE thread_id = ?", (thread_id,)
            ) as cur:
                row = await cur.fetchone()
            if row is None or row[0] != token:
                log.warning("thread %s: run finished after its lease was taken over; ignored", thread_id)
                return False
            await self.set_status(thread_id, status)
            if count_turn:
                await self.touch(thread_id, entities)
            return True

    def _lock(self, thread_id: str) -> asyncio.Lock:
        return self._locks.setdefault(thread_id, asyncio.Lock())


def _entities_json(entities: Entities | None) -> str | None:
    return None if entities is None else entities.model_dump_json(exclude_none=True)


def _record(row: Any) -> ThreadRecord:
    (thread_id, persona, principal_id, title, status, source, turns, entities, created, updated, since, _) = (
        row
    )
    return ThreadRecord(
        thread_id=thread_id,
        persona=persona,
        principal_id=principal_id,
        title=title,
        status=status,
        source=source,
        turn_count=turns,
        last_entities=Entities.model_validate(json.loads(entities)) if entities else None,
        created_at=datetime.fromisoformat(created),
        updated_at=datetime.fromisoformat(updated),
        running_since=datetime.fromisoformat(since) if since else None,
    )


def reset_threads(path: Path | None = None) -> list[Path]:
    """Delete the checkpoints file and its WAL/SHM siblings (make reset-threads). Returns what was removed."""
    path = path or get_settings().paths.checkpoints
    removed = []
    for candidate in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        if candidate.exists():
            try:
                candidate.unlink()
            except PermissionError as exc:  # Windows: the API still has the file open
                raise SystemExit(f"{candidate} is in use: stop make api first") from exc
            removed.append(candidate)
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="insurai.agent.threads")
    parser.add_argument("--reset", action="store_true", help="delete paths.checkpoints (stop make api first)")
    args = parser.parse_args(argv)
    if args.reset:
        removed = reset_threads()
        log.info("removed %s", [str(p) for p in removed] or "nothing (no checkpoints file)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
