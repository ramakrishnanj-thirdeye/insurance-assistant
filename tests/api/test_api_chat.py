"""/chat and /chat/resume over HTTP (spec 09): SSE order, interrupt flow, ownership, busy, pending review,
restart recovery. Real warehouse, scripted LLMs, private checkpoints file."""

import asyncio
import sqlite3
import threading
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from fakes import citing_synth, forbid_llm, install
from fastapi.testclient import TestClient
from sse_client import AGENT, OTHER, OWNER, WHY_PENDING, parse_sse, stream

from insurai.api.main import create_app

pytestmark = pytest.mark.integration

NOTE = "Hospital confirmed the admission by phone"
WHY = "Why is the status of CLM300210 still pending?"  # not the fast path: goes through the planner


def _names(events: list[tuple[str, dict[str, Any]]]) -> list[str]:
    return [name for name, _ in events]


def _thread(events: list[tuple[str, dict[str, Any]]]) -> str:
    assert events[0][0] == "thread"
    return str(events[0][1]["thread_id"])


def _status(client: TestClient, thread_id: str, headers: dict[str, str]) -> str:
    return str(client.get(f"/threads/{thread_id}", headers=headers).json()["status"])


def test_AC_09_02_chat_streams_thread_nodes_final_done(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    forbid_llm(monkeypatch)  # fast path
    status, events = stream(client, "/chat", {"message": "status of CLM300210"}, AGENT)
    assert status == 200
    names = _names(events)
    assert names[0] == "thread" and names[-2:] == ["final", "done"]
    assert set(names[1:-2]) <= {"node", "tool"} and "node" in names
    nodes = [d for n, d in events if n == "node"]
    assert nodes[0] == {"name": "input_guard", "status": "start"}
    assert {d["name"] for d in nodes if d["status"] == "end"} >= {"input_guard", "claim_tools", "respond"}
    assert all(d["ms"] >= 0 for d in nodes if d["status"] == "end")
    tool = next(d for n, d in events if n == "tool")
    assert (
        tool["name"] == "get_claim"
        and tool["ok"] is True
        and tool["args_redacted"] == {"claim_id": "CLM300210"}
    )
    final = events[-2][1]
    assert "[claims:CLM300210]" in final["citations"] and "CLM300210" in final["answer_markdown"]
    assert final["trace"] and _status(client, _thread(events), AGENT) == "active"
    assert client.get("/threads", headers=AGENT).json()[0]["turn_count"] == 1


def test_AC_09_03_interrupt_then_resume_approve_final_has_decision(client: TestClient) -> None:
    _, events = stream(client, "/chat", {"message": "Analyze claim CLM300210"}, AGENT)
    thread_id = _thread(events)
    assert _names(events)[-2:] == ["interrupt", "done"]
    summary = events[-2][1]["assessment_summary"]
    assert summary["claim_id"] == "CLM300210" and summary["needs_human_review"] is True
    assert _status(client, thread_id, AGENT) == "awaiting_review"

    body = {"thread_id": thread_id, "action": "approve", "note": NOTE}
    status, resumed = stream(client, "/chat/resume", body, AGENT)
    assert status == 200 and _names(resumed)[-2:] == ["final", "done"]
    final = resumed[-2][1]
    assert "Reviewer decision: **approve**" in final["answer_markdown"] and NOTE in final["answer_markdown"]
    assert final["assessment"]["review"] == {"action": "approve", "note": NOTE}
    assert _status(client, thread_id, AGENT) == "active"
    detail = client.get(f"/threads/{thread_id}", headers=AGENT).json()
    assert detail["turn_count"] == 1 and detail["pending_review"] is None
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]


def test_AC_09_07_other_customer_thread_403(client: TestClient) -> None:
    _, events = stream(client, "/chat", {"message": "status of CLM300210"}, OWNER)
    thread_id = _thread(events)
    for response in (
        client.get(f"/threads/{thread_id}", headers=OTHER),
        client.post("/chat", json={"message": "status of CLM300210", "thread_id": thread_id}, headers=OTHER),
        client.post("/chat/resume", json={"thread_id": thread_id, "action": "approve"}, headers=OTHER),
        client.patch(f"/threads/{thread_id}", json={"title": "mine now"}, headers=OTHER),
        client.delete(f"/threads/{thread_id}", headers=OTHER),
    ):
        assert response.status_code == 403
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json()["code"] == "THREAD_FORBIDDEN"


def test_AC_09_07_agent_on_customer_thread_403(client: TestClient) -> None:
    _, events = stream(client, "/chat", {"message": "status of CLM300210"}, OWNER)
    thread_id = _thread(events)
    assert client.get(f"/threads/{thread_id}", headers=AGENT).json()["code"] == "THREAD_FORBIDDEN"
    status, body = stream(client, "/chat", {"message": "status of CLM300210", "thread_id": thread_id}, AGENT)
    assert status == 403 and body["code"] == "THREAD_FORBIDDEN"


def test_AC_09_07_unknown_thread_404(client: TestClient) -> None:
    unknown = "0" * 32
    assert client.get(f"/threads/{unknown}", headers=AGENT).json()["code"] == "THREAD_NOT_FOUND"
    status, body = stream(client, "/chat", {"message": "hello", "thread_id": unknown}, AGENT)
    assert status == 404 and body["code"] == "THREAD_NOT_FOUND"
    status, body = stream(client, "/chat/resume", {"thread_id": unknown, "action": "approve"}, AGENT)
    assert status == 404 and body["code"] == "THREAD_NOT_FOUND"


def test_AC_09_09_chat_on_awaiting_review_409_with_summary(client: TestClient) -> None:
    _, events = stream(client, "/chat", {"message": "Analyze claim CLM300210"}, AGENT)
    thread_id = _thread(events)
    status, body = stream(client, "/chat", {"message": "status of CLM300210", "thread_id": thread_id}, AGENT)
    assert status == 409 and body["code"] == "REVIEW_PENDING"
    assert body["review"]["claim_id"] == "CLM300210" and body["review"]["missing_documents"]
    assert _status(client, thread_id, AGENT) == "awaiting_review"


def test_AC_09_09_resume_on_active_409_no_pending_review(client: TestClient) -> None:
    _, events = stream(client, "/chat", {"message": "status of CLM300210"}, AGENT)
    body = {"thread_id": _thread(events), "action": "approve"}
    status, problem = stream(client, "/chat/resume", body, AGENT)
    assert status == 409 and problem["code"] == "NO_PENDING_REVIEW"


async def test_AC_09_08_concurrent_chat_one_streams_other_409_busy(
    checkpoints: Path, warehouse_ready: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, gate = threading.Event(), threading.Event()

    def blocking_planner(messages: list[Any]) -> Any:
        entered.set()
        assert gate.wait(30), "test never released the planner"
        return WHY_PENDING

    install(monkeypatch, {"Plan": blocking_planner, "AnswerDraft": citing_synth})
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60) as ac:
            created = await ac.post("/chat", json={"message": "status of CLM300210"}, headers=AGENT)
            thread_id = _thread(parse_sse(created.text))
            body = {"message": WHY, "thread_id": thread_id}
            first = asyncio.create_task(ac.post("/chat", json=body, headers=AGENT))
            try:
                assert await asyncio.to_thread(entered.wait, 30)
                second = await ac.post("/chat", json=body, headers=AGENT)
                resume = await ac.post(
                    "/chat/resume", json={"thread_id": thread_id, "action": "approve"}, headers=AGENT
                )
            finally:
                gate.set()
            done = await first
            after = (await ac.get(f"/threads/{thread_id}", headers=AGENT)).json()
    assert second.status_code == 409 and second.json()["code"] == "THREAD_BUSY"
    assert resume.status_code == 409 and resume.json()["code"] == "THREAD_BUSY"
    assert done.status_code == 200 and _names(parse_sse(done.text))[-2:] == ["final", "done"]
    assert after["status"] == "active" and after["turn_count"] == 2


def test_stale_lease_is_taken_over_by_chat(client: TestClient, checkpoints: Path) -> None:
    _, events = stream(client, "/chat", {"message": "status of CLM300210"}, AGENT)
    thread_id = _thread(events)
    stale = datetime(2020, 1, 1, tzinfo=UTC).isoformat()  # far older than turn_timeout_s
    with closing(sqlite3.connect(checkpoints)) as con:
        con.execute(
            "UPDATE threads SET status = 'running', running_since = ?, run_token = 'hung' "
            "WHERE thread_id = ?",
            (stale, thread_id),
        )
        con.commit()
    status, events = stream(
        client, "/chat", {"message": "status of CLM300210", "thread_id": thread_id}, AGENT
    )
    assert status == 200 and _names(events)[-2:] == ["final", "done"]
    assert _status(client, thread_id, AGENT) == "active"


def test_graph_error_streams_error_then_done_and_frees_thread(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(messages: list[Any]) -> Any:
        raise RuntimeError("model crashed")

    install(monkeypatch, {"Plan": broken, "AnswerDraft": citing_synth})
    status, events = stream(client, "/chat", {"message": WHY}, AGENT)
    assert status == 200 and _names(events)[-2:] == ["error", "done"]
    assert events[-2][1]["code"] == "TURN_FAILED" and "crashed" not in events[-2][1]["message"]
    assert _status(client, _thread(events), AGENT) == "active"


def test_customer_cannot_resume_review(client: TestClient) -> None:
    _, events = stream(client, "/chat", {"message": "status of CLM300210"}, OWNER)
    status, body = stream(client, "/chat/resume", {"thread_id": _thread(events), "action": "approve"}, OWNER)
    assert status == 403 and body["code"] == "ACCESS_DENIED"


def test_identity_headers_required_and_must_match_body(client: TestClient) -> None:
    status, body = stream(client, "/chat", {"message": "hi"}, {})
    assert status == 400 and body["code"] == "IDENTITY_REQUIRED"
    status, body = stream(client, "/chat", {"message": "hi"}, {"X-Persona": "customer"})
    assert status == 400 and body["code"] == "IDENTITY_REQUIRED"
    status, body = stream(client, "/chat", {"message": "hi", "persona": "supervisor"}, AGENT)
    assert status == 400 and body["code"] == "IDENTITY_MISMATCH"
    status, body = stream(client, "/chat", {"message": ""}, AGENT)
    assert status == 422 and body["code"] == "VALIDATION_ERROR"


def test_AC_09_12_restart_recovers_running_threads_from_checkpoints(
    checkpoints: Path, warehouse_ready: None, scripted: Any
) -> None:
    with TestClient(create_app()) as c:
        paused = _thread(stream(c, "/chat", {"message": "Analyze claim CLM300210"}, AGENT)[1])
        plain = _thread(stream(c, "/chat", {"message": "status of CLM300210"}, AGENT)[1])
    now = datetime.now(UTC).isoformat()
    with closing(sqlite3.connect(checkpoints)) as con:  # the API stopped mid-turn on both threads
        con.execute("UPDATE threads SET status = 'running', running_since = ?, run_token = 'x'", (now,))
        con.commit()
    with TestClient(create_app()) as c:
        statuses = {t["thread_id"]: t["status"] for t in c.get("/threads", headers=AGENT).json()}
    assert statuses == {paused: "awaiting_review", plain: "active"}
