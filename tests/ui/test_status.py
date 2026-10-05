"""Status line phrases (spec 10, config/ui_status.yaml): rotation, tone, tool lines, plan summary, safety."""

import pytest
from status import (
    SAFE_PLACEHOLDERS,
    UNDERSTOOD_PLACEHOLDERS,
    badge,
    load_status,
    placeholders,
    select_tone,
    status_line,
)

from insurai.agent.graph import NODES
from insurai.observability.progress import status_args
from insurai.tools.access import load_personas

pytestmark = pytest.mark.unit

PRO = "professional"
PLAN = {"intents": ["policy_question"], "product": "Health Secure Plus", "claim_ids": [], "policy_ids": []}
CUSTOMER_NAME = "Aditya Joshi"  # the name on CUST139920 in the warehouse


def _tool(name: str, args: dict) -> dict:
    return {"name": name, "args_redacted": args}


def test_AC_10_09_node_phrases_rotate_on_each_heartbeat() -> None:
    phrases = load_status().tones[PRO].nodes["planner"]
    assert status_line("node", {"name": "planner", "status": "start"}, PRO) == phrases[0]
    lines = [status_line("heartbeat", {"node": "planner", "beat": b}, PRO) for b in range(1, 5)]
    assert lines == [phrases[b % len(phrases)] for b in range(1, 5)]
    assert lines[:2] == ["Working out which records to check", "Reading your question"]


def test_AC_10_09_tool_lines_name_the_record_or_fall_back() -> None:
    assert status_line("tool_start", _tool("get_claim", {"claim_id": "CLM300210"}), PRO) == (
        "Pulling up claim CLM300210"
    )
    hsp = _tool("search_policy", {"product": "Health Secure Plus"})
    assert status_line("tool_start", hsp, PRO) == "Searching the Health Secure Plus wording"
    assert status_line("tool_start", _tool("search_policy", {}), PRO) == "Searching the policy wording"
    docs = _tool("get_claim_documents", {"claim_id": "CLM300210"})
    assert status_line("tool_start", docs, PRO) == "Checking the claim's documents"


def test_AC_10_09_understood_after_the_planner() -> None:
    end = {"name": "planner", "status": "end", "plan": PLAN}
    assert status_line("node", end, PRO) == "Understood: policy question · Health Secure Plus"
    claim = {**PLAN, "intents": ["claim_status"], "product": None, "claim_ids": ["CLM300210"]}
    assert status_line("node", {**end, "plan": claim}, PRO) == "Understood: claim status · CLM300210"
    assert status_line("node", {**end, "plan": {**PLAN, "intents": []}}, PRO) is None


def test_AC_10_09_customer_always_gets_professional_tone() -> None:
    assert select_tone("customer", "playful") == PRO
    assert select_tone("claims_agent", "playful") == "playful"
    assert select_tone("supervisor", None) == PRO and select_tone("supervisor", "nope") == PRO
    start = {"name": "planner", "status": "start"}
    assert status_line("node", start, "playful") != status_line("node", start, PRO)


def test_AC_10_09_badges() -> None:
    assert badge("drafting", PRO) == "checking…" and badge("checking", PRO) == "checking…"
    assert badge("revising", PRO) == "revising…" and badge("verified", PRO) == "✓ verified"
    assert badge("final", PRO) is None and badge("idle", PRO) is None


def test_AC_10_09_config_covers_real_nodes_tools_and_safe_placeholders_only() -> None:
    cfg = load_status()
    tools = {t for p in load_personas().values() for t in p.tools}
    assert cfg.default_tone == PRO and {PRO, "playful"} <= set(cfg.tones)
    for tone in cfg.tones.values():
        assert set(tone.nodes) <= set(NODES) and set(tone.tools) <= tools
        assert all(tone.nodes.values()) and {"checking", "revising", "verified"} <= set(tone.badges)
        assert all(placeholders(p) == set() for ps in tone.nodes.values() for p in ps)
        assert all(placeholders(p) <= SAFE_PLACEHOLDERS for ps in tone.tools.values() for p in ps)
        assert all(placeholders(p) <= UNDERSTOOD_PLACEHOLDERS for p in tone.understood)


@pytest.mark.parametrize("tone", [PRO, "playful"])
def test_AC_10_09_no_customer_name_in_any_status_text(tone: str) -> None:
    keys = ("claim_id", "policy_id", "hospital_id", "product", "name", "city", "customer_id", "query")
    raw = dict.fromkeys(keys, CUSTOMER_NAME)
    safe = status_args(raw)  # what the API sends as args_redacted
    assert safe == {}
    names = load_status().tones[tone].tools
    lines = [status_line("tool_start", _tool(t, args), tone) for t in names for args in (safe, raw)]
    plan = {"intents": ["customer_summary"], "product": None, "claim_ids": [], "policy_ids": []}
    lines.append(status_line("node", {"name": "planner", "status": "end", "plan": plan}, tone))
    assert all(line and CUSTOMER_NAME not in line for line in lines)
