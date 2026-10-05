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
