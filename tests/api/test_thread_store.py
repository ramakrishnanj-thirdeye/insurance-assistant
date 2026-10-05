"""ThreadStore (spec 09 Thread management, ADR-009): ownership, listing, lease and recovery. No warehouse."""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from insurai.agent.schemas import Entities
from insurai.agent.threads import (
    ELLIPSIS,
    ThreadBusy,
    ThreadForbidden,
    ThreadNotFound,
    ThreadStateChanged,
    ThreadStore,
    make_title,
    reset_threads,
)

pytestmark = pytest.mark.unit

T0 = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@asynccontextmanager
async def _store(
    path: Path, clock: Clock, pending: Callable[[str], Awaitable[bool]] | None = None
) -> AsyncIterator[ThreadStore]:
    async with ThreadStore.open(path, has_pending_review=pending, clock=clock) as store:
        yield store


async def test_AC_09_10_store_lists_only_callers_threads_newest_first(tmp_path: Path) -> None:
    clock = Clock()
    async with _store(tmp_path / "c.sqlite", clock) as store:
        first = await store.create("customer", "CUST1", "status of CLM300210", "ui")
        clock.advance(1)
        await store.create("customer", "CUST2", "someone else's question", "ui")
        clock.advance(1)
        second = await store.create("customer", "CUST1", "which documents are missing?", "api")
        clock.advance(1)
        await store.create("claims_agent", "CUST1", "same principal, other persona", "api")

        mine = await store.list("customer", "CUST1")
        assert [r.thread_id for r in mine] == [second.thread_id, first.thread_id]
        clock.advance(1)
        await store.touch(first.thread_id, Entities(claim_id="CLM300210"))
        mine = await store.list("customer", "CUST1")
        assert [r.thread_id for r in mine] == [first.thread_id, second.thread_id]
        assert mine[0].turn_count == 1 and mine[0].last_entities == Entities(claim_id="CLM300210")
        assert [r.thread_id for r in await store.list("customer", "CUST1", limit=1, offset=1)] == [
            second.thread_id
        ]


def test_AC_09_10_title_pii_masked_and_truncated() -> None:
    long = "My phone is 9876543210 and I want to know why claim CLM300210 is still pending after weeks"
    title = make_title(long)
    assert "9876543210" not in title and "[PHONE_IN]" in title
    assert title.endswith(ELLIPSIS) and len(title) <= 60 + len(ELLIPSIS)
    assert make_title("  status of\nCLM300210 ") == "status of CLM300210"


async def test_AC_09_07_store_authorize_forbidden_and_not_found(tmp_path: Path) -> None:
    async with _store(tmp_path / "c.sqlite", Clock()) as store:
        record = await store.create("customer", "CUST1", "hello", "ui")
        assert (await store.authorize(record.thread_id, "customer", "CUST1")).thread_id == record.thread_id
        with pytest.raises(ThreadForbidden):
            await store.authorize(record.thread_id, "customer", "CUST2")
        with pytest.raises(ThreadForbidden):
            await store.authorize(record.thread_id, "claims_agent", "CUST1")
        with pytest.raises(ThreadNotFound):
            await store.authorize("0" * 32, "customer", "CUST1")


async def test_AC_09_08_start_run_busy_while_running(tmp_path: Path) -> None:
    async with _store(tmp_path / "c.sqlite", Clock()) as store:
        record = await store.create("claims_agent", "staff", "hello", "api")
        token = await store.start_run(record.thread_id, {"active"})
        assert (await store.get(record.thread_id)).status == "running"
        with pytest.raises(ThreadBusy):
            await store.start_run(record.thread_id, {"active"})
        assert await store.finish_run(record.thread_id, token, "awaiting_review")
        with pytest.raises(ThreadStateChanged) as info:
            await store.start_run(record.thread_id, {"active"})
        assert info.value.status == "awaiting_review"


async def test_stale_lease_is_taken_over_and_logged(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="insurai")
    clock = Clock()
    async with _store(tmp_path / "c.sqlite", clock) as store:
        record = await store.create("claims_agent", "staff", "hello", "api")
        await store.start_run(record.thread_id, {"active"}, timeout_s=300)
        clock.advance(299)
        with pytest.raises(ThreadBusy):
            await store.start_run(record.thread_id, {"active"}, timeout_s=300)
        assert not any("stale running lease" in r.getMessage() for r in caplog.records)
        clock.advance(2)  # 301 s
        token = await store.start_run(record.thread_id, {"active"}, timeout_s=300)
        assert token and (await store.get(record.thread_id)).running_since == clock.now
        assert any(
            "stale running lease" in r.getMessage() and record.thread_id in r.getMessage()
            for r in caplog.records
        )


async def test_late_finish_with_old_token_does_not_overwrite(tmp_path: Path) -> None:
    clock = Clock()
    async with _store(tmp_path / "c.sqlite", clock) as store:
        record = await store.create("claims_agent", "staff", "hello", "api")
        hung = await store.start_run(record.thread_id, {"active"}, timeout_s=300)
        clock.advance(301)
        fresh = await store.start_run(record.thread_id, {"active"}, timeout_s=300)
        assert not await store.finish_run(record.thread_id, hung, "active", count_turn=True)
        current = await store.get(record.thread_id)
        assert current.status == "running" and current.turn_count == 0
        assert await store.finish_run(record.thread_id, fresh, "active", Entities(claim_id="CLM1"), True)
        current = await store.get(record.thread_id)
        assert current.status == "active" and current.turn_count == 1 and current.running_since is None


async def test_AC_09_12_running_thread_active_after_restart(tmp_path: Path) -> None:
    path = tmp_path / "c.sqlite"
    async with _store(path, Clock()) as store:
        record = await store.create("claims_agent", "staff", "hello", "api")
        await store.set_status(record.thread_id, "running")  # the API stops mid-turn
    async with _store(path, Clock()) as store:
        assert await store.recover() == 1
        assert (await store.get(record.thread_id)).status == "active"
        assert await store.recover() == 0


async def test_AC_09_12_recover_pending_interrupt_to_awaiting_review(tmp_path: Path) -> None:
    path = tmp_path / "c.sqlite"
    async with _store(path, Clock()) as store:
        paused = await store.create("claims_agent", "staff", "Analyze claim CLM300210", "api")
        plain = await store.create("claims_agent", "staff", "status of CLM300210", "api")
        for record in (paused, plain):
            await store.set_status(record.thread_id, "running")

    async def pending(thread_id: str) -> bool:
        return thread_id == paused.thread_id

    async with _store(path, Clock(), pending) as store:
        assert await store.recover() == 2
        assert (await store.get(paused.thread_id)).status == "awaiting_review"
        assert (await store.get(plain.thread_id)).status == "active"


async def test_rename_and_delete_record(tmp_path: Path) -> None:
    async with _store(tmp_path / "c.sqlite", Clock()) as store:
        record = await store.create("customer", "CUST1", "hello", "ui")
        await store.rename(record.thread_id, "Claim CLM300210 follow-up")
        assert (await store.get(record.thread_id)).title == "Claim CLM300210 follow-up"
        await store.delete(record.thread_id)
        with pytest.raises(ThreadNotFound):
            await store.get(record.thread_id)


def test_reset_threads_removes_checkpoint_files(tmp_path: Path) -> None:
    path = tmp_path / "checkpoints.sqlite"
    for p in (path, tmp_path / "checkpoints.sqlite-wal", tmp_path / "checkpoints.sqlite-shm"):
        p.write_bytes(b"x")
    assert len(reset_threads(path)) == 3 and not list(tmp_path.iterdir())
    assert reset_threads(path) == []
