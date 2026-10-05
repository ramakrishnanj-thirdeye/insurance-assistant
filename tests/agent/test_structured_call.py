"""structured_call: validation retry, logged second failure, token accounting, Ollama num_ctx guard."""

import logging

import pytest
from fakes import install
from langchain_core.messages import HumanMessage

from insurai.agent.schemas import Plan
from insurai.llm.structured import StructuredOutputError, structured_call

pytestmark = pytest.mark.unit

GOOD = Plan(intents=[], clarification="Which product do you mean?")


def test_structured_call_retries_once_with_validation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list] = []

    def reply(messages: list) -> object:
        seen.append(messages)
        return "not json" if len(seen) == 1 else GOOD

    install(monkeypatch, {"Plan": reply})
    plan, call = structured_call("generator", Plan, [HumanMessage("hi")], "planner", "0.2.0")
    assert plan == GOOD and call.attempts == 2
    assert "failed validation" in seen[1][-1].content
    assert call.input_tokens == 120 and call.output_tokens == 60


def test_structured_call_logs_and_raises_on_second_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    install(monkeypatch, {"Plan": ["bad", "still bad"]})
    caplog.set_level(logging.ERROR, logger="insurai")
    with pytest.raises(StructuredOutputError):
        structured_call("generator", Plan, [HumanMessage("hi")], "planner", "0.2.0")
    assert any("failed validation twice" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize(("tokens", "warned"), [(int(0.9 * 8192) + 1, True), (int(0.89 * 8192), False)])
def test_ollama_ctx_near_limit_emits_warning_event(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, tokens: int, warned: bool
) -> None:
    monkeypatch.setenv("INSURAI__LLM__PROFILE", "local")
    install(monkeypatch, {"Plan": [GOOD]}, input_tokens=tokens)
    caplog.set_level(logging.WARNING, logger="insurai")
    _, call = structured_call("generator", Plan, [HumanMessage("hi")], "planner", "0.2.0")
    assert (call.ctx_warning is not None) is warned
    assert any("near num_ctx" in r.getMessage() for r in caplog.records) is warned
    if warned:
        assert call.ctx_warning == {"input_tokens": tokens, "num_ctx": 8192, "model": "qwen3:8b"}


def test_no_ctx_warning_for_anthropic_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, {"Plan": [GOOD]}, input_tokens=100_000)
    _, call = structured_call("generator", Plan, [HumanMessage("hi")], "planner", "0.2.0")
    assert call.ctx_warning is None
