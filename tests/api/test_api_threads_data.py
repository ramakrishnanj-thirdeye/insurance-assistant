"""/threads, /health, /coverage-matrix, /claims/{id}/dossier and /eval/reports (spec 09)."""

import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sse_client import AGENT, OTHER, OWNER, SUPERVISOR, stream

pytestmark = pytest.mark.integration

LONG_PII = "My phone is 9876543210 and I want to know the status of CLM300210 after all these weeks"


def _new_thread(client: TestClient, message: str, headers: dict[str, str]) -> str:
    _, events = stream(client, "/chat", {"message": message}, headers)
    return str(events[0][1]["thread_id"])


def test_AC_09_10_list_only_callers_threads_newest_first_masked_titles(client: TestClient) -> None:
    first = _new_thread(client, "status of CLM300210", OWNER)
    _new_thread(client, "status of CLM300500", OTHER)
    second = _new_thread(client, LONG_PII, OWNER)
    _new_thread(client, "status of CLM300210", AGENT)

    listed = client.get("/threads", headers=OWNER).json()
    assert [t["thread_id"] for t in listed] == [second, first]
    title = listed[0]["title"]
    assert "9876543210" not in title and "[PHONE_IN]" in title
    assert title.endswith("…") and len(title) <= 61
    assert listed[1]["title"] == "status of CLM300210"
    page = client.get("/threads", params={"limit": 1, "offset": 1}, headers=OWNER).json()
    assert [t["thread_id"] for t in page] == [first]


def test_rename_thread(client: TestClient) -> None:
    thread_id = _new_thread(client, "status of CLM300210", AGENT)
    renamed = client.patch(f"/threads/{thread_id}", json={"title": "CLM300210 escalation"}, headers=AGENT)
    assert renamed.status_code == 200 and renamed.json()["title"] == "CLM300210 escalation"


def _checkpoint_rows(path: Path, thread_id: str) -> int:
    with closing(sqlite3.connect(path)) as con:
        return sum(
            con.execute(f"SELECT count(*) FROM {table} WHERE thread_id = ?", (thread_id,)).fetchone()[0]
            for table in ("checkpoints", "writes")
        )


def test_AC_09_11_delete_removes_record_and_checkpoints(client: TestClient, checkpoints: Path) -> None:
    thread_id = _new_thread(client, "Analyze claim CLM300210", AGENT)
    assert _checkpoint_rows(checkpoints, thread_id) > 0
    response = client.delete(f"/threads/{thread_id}", headers=AGENT)
    assert response.status_code == 204 and response.content == b""
    assert client.get(f"/threads/{thread_id}", headers=AGENT).json()["code"] == "THREAD_NOT_FOUND"
    assert _checkpoint_rows(checkpoints, thread_id) == 0
    assert client.get("/threads", headers=AGENT).json() == []


def test_AC_09_01_docs_served_and_health_ok(client: TestClient, index_path: Path) -> None:
    assert client.get("/docs").status_code == 200
    assert "/chat" in client.get("/openapi.json").json()["paths"]
    health = client.get("/health").json()
    assert health["warehouse"] == "ok" and health["qdrant"] == "ok" and health["status"] == "ok"
    assert health["as_of"] == "2026-10-01" and health["coverage_status"] == "reviewed"
    assert health["llm_profile"] and health["versions"]["prompts"]["planner"]


def test_health_reports_missing_index(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from insurai.retrieval import search
    from insurai.settings import get_settings

    monkeypatch.setattr(get_settings().paths, "qdrant_path", tmp_path / "no-index")
    search.close_readers()
    health = client.get("/health").json()
    assert health["status"] == "degraded" and health["qdrant"].startswith("error:")


def test_AC_09_05_dossier_without_narrate_under_500ms(client: TestClient) -> None:
    client.get("/claims/CLM300210/dossier", headers=AGENT)  # warm the DuckDB and settings caches
    start = time.perf_counter()
    response = client.get("/claims/CLM300210/dossier", headers=AGENT)
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert response.status_code == 200, response.text
    assert elapsed_ms < 500, f"dossier took {elapsed_ms:.0f} ms"
    body = response.json()
    assert body["claim_id"] == "CLM300210" and body["view"] == "full" and body["needs_human_review"] is True
    assert {"[claims:CLM300210]", "[claim_documents:CLM300210]"} <= {s["label"] for s in body["sources"]}


def test_dossier_customer_view_and_other_customer_403(client: TestClient) -> None:
    own = client.get("/claims/CLM300210/dossier", headers=OWNER).json()
    assert own["view"] == "customer" and own["escalation_reasons"] == []
    assert "fraud_risk_score" not in own["facts"]
    other = client.get("/claims/CLM300210/dossier", headers=OTHER)
    assert other.status_code == 403 and other.json()["code"] == "ACCESS_DENIED"


def test_dossier_unknown_claim_404_narrate_501_and_query_mismatch_400(client: TestClient) -> None:
    assert client.get("/claims/CLM999999/dossier", headers=AGENT).json()["code"] == "NOT_FOUND"
    narrate = client.get("/claims/CLM300210/dossier", params={"narrate": True}, headers=AGENT)
    assert narrate.status_code == 501 and narrate.json()["code"] == "NOT_IMPLEMENTED"
    mismatch = client.get("/claims/CLM300210/dossier", params={"persona": "supervisor"}, headers=AGENT)
    assert mismatch.status_code == 400 and mismatch.json()["code"] == "IDENTITY_MISMATCH"


def test_coverage_matrix_cells_and_unknown_product_404(client: TestClient) -> None:
    cells = client.get(
        "/coverage-matrix",
        params={"product": "Health Secure Plus", "attribute": "waiting_period"},
        headers=AGENT,
    )
    assert cells.status_code == 200 and cells.json()["cells"] and cells.json()["sources"]
    unknown = client.get("/coverage-matrix", params={"product": "Space Cover"}, headers=AGENT)
    assert unknown.status_code == 404 and unknown.json()["code"] == "NOT_FOUND"


def test_eval_reports_list_and_detail(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from insurai.settings import get_settings

    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "fast_20261005T035526Z.json").write_text(
        '{"suite": "fast", "created_at": "2026-10-05T03:55:26+00:00", "git_sha": "abc",'
        ' "slices": {"routing": {"metrics": {"items": 68, "intent_accuracy": 0.8971, "by_slice": {}}}}}',
        encoding="utf-8",
    )
    (reports / "notes.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(get_settings().paths, "eval_reports", reports)

    listed: list[dict[str, Any]] = client.get("/eval/reports", headers=AGENT).json()
    assert [r["run_id"] for r in listed] == ["fast_20261005T035526Z"]
    assert listed[0]["headline"] == {"routing": {"items": 68, "intent_accuracy": 0.8971}}
    assert client.get("/eval/reports/fast_20261005T035526Z", headers=SUPERVISOR).json()["git_sha"] == "abc"
    for bad in ("notes", "..%2Fsettings", "fast_20261005T000000Z"):
        assert client.get(f"/eval/reports/{bad}", headers=AGENT).status_code == 404


@pytest.mark.parametrize("path", ["/eval/reports", "/eval/reports/fast_20261005T035526Z"])
def test_eval_reports_staff_only_customer_403_missing_identity_400(client: TestClient, path: str) -> None:
    customer = client.get(path, headers=OWNER)
    assert customer.status_code == 403 and customer.json()["code"] == "ACCESS_DENIED"
    anonymous = client.get(path)
    assert anonymous.status_code == 400 and anonymous.json()["code"] == "IDENTITY_REQUIRED"


def test_health_needs_no_identity(client: TestClient) -> None:
    assert client.get("/health").status_code == 200
