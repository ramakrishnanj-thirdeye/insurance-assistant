"""Spec 08 eval hooks: the reusable V7 phase-2 judge, claim_analysis V7, and the guardrails slice."""

import json
import re
from typing import Any

import pytest
from fakes import citing_synth, install, plan_of, planner_script, verdicts

from insurai.agent.schemas import Evidence
from insurai.eval import claim_analysis
from insurai.eval import guardrails as slice_mod
from insurai.eval.groundedness import judge_rows, v7_metrics, verifier_pass_rates
from insurai.eval.run import SLICES
from insurai.settings import get_settings
from insurai.tools.schemas import SourceRef

MANDATED = "Final decision depends on complete claim assessment."
S15_LABEL = "[All products §15 Training FAQ Q1]"
PRECEDENCE = (
    "Your policy schedule governs this policy's numbers; the product wording describes the general terms."
)


def _ev() -> list[Evidence]:
    ref = SourceRef(kind="policy", label="[Health Secure Plus §4 Waiting Period]")
    return [
        Evidence(intent_id="i1", worker="w", kind="RetrievalResult", payload={}, sources=[ref], summary="")
    ]


@pytest.mark.unit
def test_AC_08_12_judge_rows_judges_only_V7_intents_and_reports_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install(monkeypatch, {"ClaimVerdicts": verdicts(lambda claim: claim == "Claim a.")})
    rows = [
        {"id": "P1", "answer": "Claim a.", "intents": ["policy_question"]},
        {"id": "C1", "answer": "Claim b. Claim c.", "intents": ["claim_analysis", "claim_status"]},
        {"id": "S1", "answer": "z", "intents": ["claim_status"]},  # not a V7 intent: never judged
        {"id": "E1", "answer": "", "intents": ["policy_question"]},  # no answer: never judged
    ]
    judge_rows(rows, {r["id"]: _ev() for r in rows})
    assert [r.get("v7_passed") for r in rows] == [True, False, None, None]
    assert rows[1]["v7_unsupported"] == ["Claim b.", "Claim c."]
    assert v7_metrics(rows) == {
        "v7_judged": 2,
        "v7_pass_rate": 0.5,
        "faithfulness": 0.3333,  # 1 of 3 claims supported
        "faithfulness_judged": 0.3333,
        "v7_verbatim_share": 0.0,
        "v7_claims_total": 3,
        "v7_verbatim_total": 0,
        "v7_unsupported_total": 2,
        "v7_excluded_total": 0,
        "v7_judge_errors": 0,
    }


@pytest.mark.unit
def test_verifier_pass_rates_ignore_skipped_checks() -> None:
    rows = [
        {"checks": [{"check": "V1", "passed": True}, {"check": "V7", "passed": True, "skipped": True}]},
        {"checks": [{"check": "V1", "passed": False}, {"check": "V7", "passed": False}]},
    ]
    assert verifier_pass_rates(rows) == {"V1": 0.5, "V7": 0.0}


@pytest.mark.unit
def test_guardrails_items_reuse_EVAL029_EVAL030_and_score_answers() -> None:
    items = {i.id: i for i in slice_mod.load_items()}
    assert set(items) == {"EVAL029", "EVAL030", "GRD001"} and "guardrails" in SLICES
    assert (
        items["EVAL030"].tags == ["common_section", "guarantee", "guarantee"]
        or "guarantee" in items["EVAL030"].tags
    )
    assert not items["EVAL029"].must_refuse and not items["EVAL030"].must_refuse
    answer = f"I can't promise an outcome. {MANDATED} [All products §15 Training FAQ Q1]"
    assert slice_mod.score(items["EVAL030"], answer) == {
        "refused": False,
        "s15_cited": True,
        "mandated_wording": True,
    }
    refused = slice_mod.score(items["EVAL030"], slice_mod.guardrails()["refusals"]["GUARANTEE_REQUEST"])
    assert refused["refused"] and not refused["s15_cited"]
    no_period = f"Final decision depends on complete claim assessment {S15_LABEL}."
    assert slice_mod.score(items["EVAL029"], no_period)["mandated_wording"]
    assert slice_mod.score(items["GRD001"], f"0 days; 30 days. {PRECEDENCE}")["conflict_rendered"]


@pytest.mark.integration
def test_GRD001_policy_is_health_secure_plus_with_a_0_day_schedule_waiting_period() -> None:
    if not get_settings().paths.warehouse.exists():
        pytest.skip("data/warehouse.duckdb not built: run `make data`")
    from insurai.tools.base import fetch_one

    row = fetch_one(
        "SELECT product_name, waiting_period_days FROM silver.policies WHERE policy_id = ?", ["POL200025"]
    )
    assert row == {"product_name": "Health Secure Plus", "waiting_period_days": 0}


@pytest.mark.integration
def test_guardrails_slice_end_to_end_scripted(index_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    if not get_settings().paths.warehouse.exists():
        pytest.skip("data/warehouse.duckdb not built: run `make data`")
    monkeypatch.setenv("INSURAI__LLM__PROFILE", "local")  # V7 off in the request path: eval phase 2 only
    get_settings.cache_clear()
    order: list[str] = []

    def synth(messages: list[Any]) -> str:
        order.append("generate")
        return citing_synth(messages)

    def judge(messages: list[Any]) -> dict[str, Any]:
        order.append("judge")
        return verdicts()(messages)

    plans = planner_script(
        {
            "cashless authorization": plan_of(("policy_question", {"product": "Health Secure Plus"})),
            "guarantee my claim": plan_of(("policy_question", {"product": "Senior Health Shield"})),
            "waiting period on POL200025": plan_of(
                ("policy_details", {"policy_id": "POL200025"}), question="What's the waiting period?"
            ),
        }
    )
    install(monkeypatch, {"Plan": plans, "Text": synth, "ClaimVerdicts": judge})
    m = slice_mod.run_slice()["metrics"]
    assert m["items"] == 3 and m["errors"] == []
    assert m["not_refused"] == 1.0 and m["s15_cited"] == 1.0 and m["mandated_wording"] == 1.0
    assert m["conflict_rendered"] == 1.0 and m["v7_judged"] == 2 and m["v7_pass_rate"] == 1.0
    # GRD001 is a template answer: not judged. The guarantee answers hold only fixed sentences and labels,
    # so no claim is left to send and the judge is never called (AC-08-22)
    assert order == ["generate", "generate"]


@pytest.mark.integration
def test_claim_analysis_reports_v7_on_narratives_in_phase_2(
    index_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not get_settings().paths.warehouse.exists():
        pytest.skip("data/warehouse.duckdb not built: run `make data`")

    def narrator(messages: list[Any]) -> str:
        system = str(messages[0].content)
        if "<draft>" in system:
            return re.search(r"<draft>(.*)</draft>", system, re.DOTALL).group(1)  # type: ignore[union-attr]
        data = json.loads(re.search(r"<assessment>(.*)</assessment>", system, re.DOTALL).group(1))  # type: ignore[union-attr]
        return f"Position. {data['claim_citation']}"

    seen: list[str] = []

    def judge(messages: list[Any]) -> dict[str, Any]:
        seen.append(str(messages[0].content))
        return verdicts()(messages)

    install(
        monkeypatch,
        {
            "Text": narrator,
            "InventedFindings": lambda m: {"invented": [], "count": 0},
            "ClaimVerdicts": judge,
        },
    )
    monkeypatch.setattr(claim_analysis, "SOURCES", ("claim_analysis_seed.jsonl",))
    m = claim_analysis.run_slice()["metrics"]
    assert m["v7_judged"] == 3 and m["v7_pass_rate"] == 1.0
    assert all('"narrative"' not in s for s in seen), "the narrative is not its own evidence"
