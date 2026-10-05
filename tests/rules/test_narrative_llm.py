"""Live-model AC-07-07 (`make test-llm`): the generator's narrative for CA001-CA003 mentions every blocker
(labels.must_mention) and the judge finds no invented findings. Also the false-premise correction."""

import os
from typing import Any

import httpx
import pytest
from claim_items import item_ids, seed_items

from insurai.agent.dossier import analyze
from insurai.eval.claim_analysis import judge_invented, mention_recall
from insurai.rules.schemas import ClaimAssessment
from insurai.settings import get_settings
from insurai.tools.schemas import ToolContext

pytestmark = [pytest.mark.llm, pytest.mark.integration]

_API_KEY = os.environ.get("ANTHROPIC_API_KEY")  # read before the autouse fixture scrubs the environment


@pytest.fixture(params=["local", "api-lite"])
def profile(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, warehouse_ready: None) -> str:
    monkeypatch.setenv("INSURAI__LLM__PROFILE", request.param)
    if request.param == "local":
        try:
            httpx.get(f"{get_settings().ollama_base_url}/api/tags", timeout=3).raise_for_status()
        except httpx.HTTPError:
            pytest.skip("Ollama not reachable")
    elif _API_KEY:
        monkeypatch.setenv("ANTHROPIC_API_KEY", _API_KEY)
    else:
        pytest.skip("no ANTHROPIC_API_KEY")
    get_settings.cache_clear()
    return str(request.param)


def _ctx() -> ToolContext:
    return ToolContext(persona="claims_agent", as_of=get_settings().as_of_date, trace_id="llm-ac0707")


@pytest.mark.parametrize("item", seed_items(), ids=item_ids(seed_items()))
def test_AC_07_07_narrative_mentions_blockers_and_judge_finds_none_invented(
    profile: str, index_path: Any, item: dict[str, Any]
) -> None:
    result = analyze(_ctx(), item["labels"]["claim_id"], narrate=True, question=item["turns"][-1]["content"])
    assert isinstance(result, ClaimAssessment) and result.narrative
    assert mention_recall(item["labels"]["must_mention"], result.narrative) == 1.0, result.narrative
    if item["id"] == "CA001":
        assert "₹58,119" in result.narrative
    judged = judge_invented(result, result.narrative)
    assert judged.count == 0, (judged.invented, result.narrative)


def test_false_premise_corrected_by_the_live_narrative(profile: str, index_path: Any) -> None:
    result = analyze(_ctx(), "CLM300210", narrate=True, question="Why is CLM300210 pending?")
    assert isinstance(result, ClaimAssessment) and result.narrative
    assert result.narrative.startswith("CLM300210 is Approved, not pending [claims:CLM300210].")
