"""Sync client for the spec 09 API, used by the Streamlit UI (spec 10) and later by `make demo-check`.

Identity travels as X-Persona / X-Principal-Id headers on every call. `chat` and `resume` yield the SSE
events as (event, data) pairs. A 4xx before the stream opens raises ApiProblem with the problem+json code.
A stream that stays silent longer than `agent.turn_timeout_s + 30` raises ApiProblem("TIMEOUT"), so the UI
shows an error instead of hanging.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
from httpx_sse import connect_sse

from insurai.settings import get_settings

Event = tuple[str, dict[str, Any]]
TIMEOUT_GRACE_S = 30.0


class ApiProblem(Exception):
    def __init__(self, status: int, code: str, detail: str, **extra: Any) -> None:
        super().__init__(f"{status} {code}: {detail}")
        self.status, self.code, self.detail, self.extra = status, code, detail, extra

    @classmethod
    def of(cls, response: httpx.Response) -> "ApiProblem":
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        status = body.pop("status", response.status_code)
        code = body.pop("code", "HTTP_ERROR")
        detail = body.pop("detail", response.reason_phrase)
        for key in ("type", "title"):
            body.pop(key, None)
        return cls(status, code, str(detail), **body)


@dataclass(frozen=True)
class Identity:
    persona: str
    principal_id: str | None = None  # the customer_id for customer; None lets staff default to `staff`

    def headers(self) -> dict[str, str]:
        headers = {"X-Persona": self.persona}
        if self.principal_id:
            headers["X-Principal-Id"] = self.principal_id
        return headers


def read_timeout_s() -> float:
    return get_settings().agent.turn_timeout_s + TIMEOUT_GRACE_S


@contextmanager
def _transport_errors() -> Iterator[None]:
    try:
        yield
    except httpx.TimeoutException as exc:
        raise ApiProblem(
            504, "TIMEOUT", f"No response from the API within {read_timeout_s():.0f} s; try again."
        ) from exc
    except httpx.TransportError as exc:
        raise ApiProblem(
            503, "API_UNAVAILABLE", f"Cannot reach the API ({exc}). Is `make api` running?"
        ) from exc


class ApiClient:
    def __init__(self, http: httpx.Client) -> None:
        self.http = http

    @classmethod
    def from_settings(cls) -> "ApiClient":
        timeout = httpx.Timeout(10.0, read=read_timeout_s())
        return cls(httpx.Client(base_url=get_settings().ui.api_url, timeout=timeout))

    def _json(self, method: str, path: str, ident: Identity | None = None, **kwargs: Any) -> Any:
        with _transport_errors():
            response = self.http.request(method, path, headers=ident.headers() if ident else None, **kwargs)
        if response.status_code >= 400:
            raise ApiProblem.of(response)
        return response.json() if response.content else None

    def health(self) -> dict[str, Any]:
        return self._json("GET", "/health")

    def list_threads(self, ident: Identity, limit: int = 20) -> list[dict[str, Any]]:
        return self._json("GET", "/threads", ident, params={"limit": limit})

    def get_thread(self, thread_id: str, ident: Identity) -> dict[str, Any]:
        return self._json("GET", f"/threads/{thread_id}", ident)

    def rename_thread(self, thread_id: str, title: str, ident: Identity) -> dict[str, Any]:
        return self._json("PATCH", f"/threads/{thread_id}", ident, json={"title": title})

    def delete_thread(self, thread_id: str, ident: Identity) -> None:
        self._json("DELETE", f"/threads/{thread_id}", ident)

    def chat(
        self, message: str, thread_id: str | None, ident: Identity, source: str = "ui"
    ) -> Iterator[Event]:
        body = {"message": message, "thread_id": thread_id, "source": source}
        return self._stream("/chat", body, ident)

    def resume(self, thread_id: str, action: str, note: str, ident: Identity) -> Iterator[Event]:
        return self._stream("/chat/resume", {"thread_id": thread_id, "action": action, "note": note}, ident)

    def _stream(self, path: str, body: dict[str, Any], ident: Identity) -> Iterator[Event]:
        with (
            _transport_errors(),
            connect_sse(self.http, "POST", path, json=body, headers=ident.headers()) as es,
        ):
            if not es.response.headers.get("content-type", "").startswith("text/event-stream"):
                es.response.read()
                raise ApiProblem.of(es.response)
            for sse in es.iter_sse():
                if sse.event in ("", "message", "ping"):
                    continue
                yield sse.event, json.loads(sse.data) if sse.data else {}


@dataclass
class TurnView:
    """What one streamed turn produced: a pure fold over its events, rendered by the UI."""

    thread_id: str | None = None
    progress: list[tuple[str, dict[str, Any]]] = field(default_factory=list)  # node and tool events
    answer: str | None = None
    citations: list[str] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    interrupt: dict[str, Any] | None = None
    error: str | None = None
    done: bool = False

    def apply(self, event: str, data: dict[str, Any]) -> None:
        match event:
            case "thread":
                self.thread_id = data.get("thread_id")
            case "node" | "tool":
                self.progress.append((event, data))
            case "final":
                self.answer = data.get("answer_markdown", "")
                self.citations = list(data.get("citations", []))
                self.trace = list(data.get("trace", []))
            case "interrupt":
                self.interrupt = data.get("assessment_summary") or {}
            case "error":
                self.error = data.get("message") or data.get("code") or "The turn failed."
            case "done":
                self.done = True
