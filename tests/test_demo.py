"""`make demo` launcher (spec 10, AC-10-16): warm-up with keep_alive, API without --reload, stale port."""

import json
from typing import Any

import httpx
import pytest

from insurai import demo
from insurai.settings import get_settings

pytestmark = pytest.mark.unit


def test_AC_10_16_local_profile_warms_qwen_once_with_keep_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INSURAI__LLM__PROFILE", "local")
    assert demo.demo_models(get_settings(), v7_live=False) == [("qwen3:8b", "30m")]
    assert ("llama3.1:8b", None) in demo.demo_models(get_settings(), v7_live=True)


def test_AC_10_16_api_profile_has_nothing_to_warm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INSURAI__LLM__PROFILE", "api-lite")
    assert demo.demo_models(get_settings(), v7_live=True) == []


def test_AC_10_16_warm_up_posts_keep_alive_and_reports_failures() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        return httpx.Response(200 if body["model"] == "qwen3:8b" else 404, json={})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        failed = demo.warm_up(http, "http://ollama:11434/", [("qwen3:8b", "30m"), ("missing:1b", None)])
    assert failed == ["missing:1b"]
    assert bodies[0] == {"model": "qwen3:8b", "prompt": "", "stream": False, "keep_alive": "30m"}
    assert "keep_alive" not in bodies[1]


def test_AC_10_16_api_runs_without_reload_and_commands_are_argument_lists() -> None:
    cmd = demo.api_command("http://127.0.0.1:8000")
    assert "--reload" not in cmd and cmd[-4:] == ["--host", "127.0.0.1", "--port", "8000"]
    ui = demo.ui_command()
    assert ui[2:4] == ["streamlit", "run"] and ui[4].endswith("app.py")  # one argument even with spaces


def test_AC_10_16_stale_api_on_the_port_stops_before_starting(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[Any] = []
    monkeypatch.setattr(demo, "healthy", lambda http, url: True)
    monkeypatch.setattr(demo.subprocess, "Popen", lambda *a, **k: started.append(a))
    assert demo.main(["--no-browser"]) == 1 and started == []
