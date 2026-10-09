"""Live-model checks (`make test-llm`): profile smoke, real planner clarification, token counts.

The local profile needs Ollama with qwen3:8b; api-lite needs ANTHROPIC_API_KEY (skipped until a key exists).
"""

import os
from typing import Any

import httpx
import pytest

from insurai.agent.runner import run_turn
from insurai.eval.routing import plan_only
from insurai.settings import get_settings
from insurai.tools.messages import guardrails

pytestmark = [pytest.mark.llm, pytest.mark.integration]

_API_KEY = os.environ.get("ANTHROPIC_API_KEY")  # read before the autouse fixture scrubs the environment


def _use_profile(monkeypatch: pytest.MonkeyPatch, profile: str) -> None:
    monkeypatch.setenv("INSURAI__LLM__PROFILE", profile)
    if profile == "local":
        try:
            httpx.get(f"{get_settings().ollama_base_url}/api/tags", timeout=3).raise_for_status()
        except httpx.HTTPError:
            pytest.skip("Ollama not reachable")
    elif _API_KEY:
        monkeypatch.setenv("ANTHROPIC_API_KEY", _API_KEY)
    else:
        pytest.skip("no ANTHROPIC_API_KEY")
    get_settings.cache_clear()


@pytest.mark.parametrize("profile", ["local", "api-lite"])
@pytest.mark.usefixtures("warehouse_ready", "index_path")
def test_AC_06_10_profile_smoke(monkeypatch: pytest.MonkeyPatch, profile: str) -> None:
    _use_profile(monkeypatch, profile)
    plan = plan_only(
        "Is drunk driving covered under Motor Protect Comprehensive?", "claims_agent", None, "smoke"
    )
    assert plan is not None and [i.type for i in plan.intents] == ["policy_question"]
    assert plan.intents[0].entities.product == "Motor Protect Comprehensive"


@pytest.mark.usefixtures("warehouse_ready", "index_path")
def test_AC_06_06_real_planner_asks_for_the_product(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_profile(monkeypatch, "local")
    plan = plan_only("What is the waiting period?", "claims_agent", None, "ac06")
    assert plan is not None and not plan.intents
    assert plan.clarification is not None and "product" in plan.clarification.lower()


@pytest.mark.usefixtures("index_path")
def test_AC_06_09_real_model_reports_tokens_for_every_llm_call(
    monkeypatch: pytest.MonkeyPatch, graph: Any
) -> None:
    _use_profile(monkeypatch, "local")
    result = run_turn(graph, "llm-ac09", "Which documents are still missing for CLM300500?", "claims_agent")
    llm = [e for e in result.trace if e.kind == "llm"]
    assert llm, "expected planner and synthesizer calls"
    for e in llm:
        assert e.data["input_tokens"] and e.data["output_tokens"], e.data
        assert e.data["model"] == "qwen3:8b" and e.data["latency_ms"] > 0


@pytest.mark.usefixtures("index_path")
def test_AC_08_09_conflict_rendering_live(monkeypatch: pytest.MonkeyPatch, graph: Any) -> None:
    """Real planner and synthesizer: POL200025 (Health Secure Plus) has a schedule waiting period of 0 days,
    the wording §4 says 30 days. The answer shows both with the precedence sentence (by the model or by the
    deterministic completion)."""
    _use_profile(monkeypatch, "local")
    result = run_turn(graph, "llm-ac0809", "What's the waiting period on POL200025?", "claims_agent")
    answer = result.answer_markdown
    assert "0 days" in answer and "30 days" in answer, answer
    assert guardrails()["conflict_rendering"]["precedence_sentence"] in answer, answer
    assert "[policies:POL200025]" in answer and "[Health Secure Plus §4 Waiting Period]" in answer, answer
