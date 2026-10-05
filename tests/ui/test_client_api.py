"""The UI's ApiClient against the real app (TestClient is an httpx.Client): spec 10 flows end to end."""

from typing import Any

import pytest

from insurai.api.client import ApiClient, ApiProblem, Identity, TurnView

pytestmark = pytest.mark.integration

AGENT = Identity("claims_agent", "asha")
OWNER = Identity("customer", "CUST139920")
OTHER = Identity("customer", "CUST000001")
NOTE = "Documents verified by phone"


def _turn(events: Any) -> TurnView:
    view = TurnView()
    for event, data in events:
        view.apply(event, data)
    return view


def test_AC_10_03_review_resume_shows_decision_in_final_answer(client: Any) -> None:
    api = ApiClient(client)
    paused = _turn(api.chat("Analyze claim CLM300210", None, AGENT))
    assert paused.interrupt is not None and paused.interrupt["claim_id"] == "CLM300210"
    assert paused.answer is None and paused.done
    assert any(e == "node" for e, _ in paused.progress)

    assert api.get_thread(paused.thread_id, AGENT)["pending_review"] is not None
    with pytest.raises(ApiProblem) as exc:
        list(api.chat("And the documents?", paused.thread_id, AGENT))
    assert exc.value.code == "REVIEW_PENDING" and exc.value.extra["review"]["claim_id"] == "CLM300210"

    resumed = _turn(api.resume(paused.thread_id, "override", NOTE, AGENT))
    assert resumed.answer is not None and resumed.error is None
    assert "Reviewer decision: **override**" in resumed.answer and NOTE in resumed.answer
    assert resumed.trace


def test_AC_10_07_threads_listed_only_for_current_identity_and_detail_restores_messages_and_trace(
    client: Any,
) -> None:
    api = ApiClient(client)
    mine = _turn(api.chat("Why is CLM300210 pending?", None, OWNER))
    agents = _turn(api.chat("Why is CLM300210 pending?", None, AGENT))
    assert mine.answer and agents.answer

    assert [t["thread_id"] for t in api.list_threads(OWNER)] == [mine.thread_id]
    assert [t["thread_id"] for t in api.list_threads(AGENT)] == [agents.thread_id]
    assert api.list_threads(OTHER) == []

    detail = api.get_thread(mine.thread_id, OWNER)
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][-1]["content"] == mine.answer
    assert detail["last_trace"] and detail["pending_review"] is None
    with pytest.raises(ApiProblem) as exc:
        api.get_thread(mine.thread_id, OTHER)
    assert exc.value.status == 403 and exc.value.code == "THREAD_FORBIDDEN"


def test_rename_and_delete_through_client(client: Any) -> None:
    api = ApiClient(client)
    view = _turn(api.chat("Why is CLM300210 pending?", None, AGENT))
    assert api.rename_thread(view.thread_id, "Pending check", AGENT)["title"] == "Pending check"
    api.delete_thread(view.thread_id, AGENT)
    assert api.list_threads(AGENT) == []
