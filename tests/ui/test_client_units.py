"""ApiClient over httpx MockTransport and the TurnView fold: no server, no network."""

import json
from collections.abc import Callable

import httpx
import pytest

from insurai.api.client import ApiClient, ApiProblem, Identity, TurnView, read_timeout_s
from insurai.settings import get_settings

pytestmark = pytest.mark.unit

AGENT = Identity("claims_agent")


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> ApiClient:
    return ApiClient(httpx.Client(base_url="http://api", transport=httpx.MockTransport(handler)))


def _sse(*events: tuple[str, dict]) -> httpx.Response:
    body = "".join(f"event: {e}\ndata: {json.dumps(d)}\n\n" for e, d in events)
    return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})


def test_read_timeout_is_turn_timeout_plus_grace() -> None:
    expected = get_settings().agent.turn_timeout_s + 30
    assert read_timeout_s() == expected
    api = ApiClient.from_settings()
    try:
        assert api.http.timeout.read == expected
    finally:
        api.http.close()


def test_dead_stream_read_timeout_raises_timeout_problem() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("silent stream", request=request)

    with pytest.raises(ApiProblem) as exc:
        list(_client(handler).chat("hello", None, AGENT))
    assert exc.value.code == "TIMEOUT" and exc.value.status == 504


def test_unreachable_api_raises_api_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ApiProblem) as exc:
        _client(handler).health()
    assert exc.value.code == "API_UNAVAILABLE"


def test_problem_json_before_stream_raises_api_problem_with_extras() -> None:
    review = {"claim_id": "CLM300210"}

    def handler(request: httpx.Request) -> httpx.Response:
        body = {"type": "urn:x", "title": "t", "status": 409, "code": "REVIEW_PENDING", "detail": "d"}
        return httpx.Response(409, json={**body, "review": review})

    with pytest.raises(ApiProblem) as exc:
        list(_client(handler).chat("hello", "t1", AGENT))
    assert (exc.value.status, exc.value.code, exc.value.extra) == (409, "REVIEW_PENDING", {"review": review})


def test_identity_headers_sent_per_call() -> None:
    seen: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers)
        return httpx.Response(200, json=[])

    api = _client(handler)
    api.list_threads(Identity("customer", "CUST139920"))
    api.list_threads(AGENT)
    assert seen[0]["x-persona"] == "customer" and seen[0]["x-principal-id"] == "CUST139920"
    assert seen[1]["x-persona"] == "claims_agent" and "x-principal-id" not in seen[1]


def test_stream_events_fold_into_turn_view() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["source"] == "ui"
        return _sse(
            ("thread", {"thread_id": "t1"}),
            ("node", {"name": "planner", "status": "start"}),
            ("node", {"name": "planner", "status": "end", "ms": 12.0}),
            ("tool", {"name": "get_claim", "ms": 3.0, "ok": True}),
            ("final", {"answer_markdown": "Approved [CLM300210]", "citations": ["CLM300210"], "trace": [{}]}),
            ("done", {}),
        )

    view = TurnView()
    for event, data in _client(handler).chat("status?", None, AGENT):
        view.apply(event, data)
    assert view.thread_id == "t1" and view.done
    assert [e for e, _ in view.progress] == ["node", "node", "tool"]
    assert view.answer == "Approved [CLM300210]" and view.citations == ["CLM300210"] and view.trace == [{}]


def test_turn_view_interrupt_and_error() -> None:
    view = TurnView()
    view.apply("interrupt", {"assessment_summary": {"claim_id": "CLM1"}})
    view.apply("error", {"code": "TURN_FAILED", "message": "could not finish"})
    assert view.interrupt == {"claim_id": "CLM1"} and view.error == "could not finish" and view.answer is None
