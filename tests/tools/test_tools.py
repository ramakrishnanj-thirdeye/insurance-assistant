"""Acceptance checks for the spec 05 tools against the real warehouse and a private policy index."""

import json
import random
from collections.abc import Iterator
from typing import Any

import duckdb
import pytest
from pydantic import BaseModel
from tool_ids import KNOWN_CLAIM, KNOWN_HOSPITAL, KNOWN_OWNER, KNOWN_POLICY, make_ctx

from insurai.retrieval.schemas import RetrievalResult
from insurai.tools import access, sources
from insurai.tools.registry import TOOLS
from insurai.tools.schemas import (
    AccessDenied,
    ClaimView,
    CustomerSummary,
    Disambiguation,
    DocumentChecklist,
    HospitalCheck,
    InteractionHistory,
    NotFound,
    PolicyView,
)

pytestmark = pytest.mark.integration

HIDDEN = ("fraud_risk_score", "manual_review_flag", "risk_segment", "customer_name")

# tool -> (found args, expected type, not-found args, bad-format args)
CASES: dict[str, tuple[dict[str, Any], type[BaseModel], dict[str, Any], dict[str, Any]]] = {
    "get_claim": ({"claim_id": KNOWN_CLAIM}, ClaimView, {"claim_id": "CLM999999"}, {"claim_id": "CLM30021"}),
    "get_claim_documents": (
        {"claim_id": KNOWN_CLAIM},
        DocumentChecklist,
        {"claim_id": "CLM999999"},
        {"claim_id": "claim-300210"},
    ),
    "get_claim_interactions": (
        {"claim_id": KNOWN_CLAIM},
        InteractionHistory,
        {"claim_id": "CLM999999"},
        {"claim_id": "CLM3002100"},
    ),
    "get_policy": (
        {"policy_id": KNOWN_POLICY},
        PolicyView,
        {"policy_id": "POL999999"},
        {"policy_id": "P218917"},
    ),
    "get_customer_summary": (
        {"customer_id": KNOWN_OWNER},
        CustomerSummary,
        {"customer_id": "CUST999999"},
        {"customer_id": "CUST13992"},
    ),
    "check_hospital": (
        {"hospital_id": KNOWN_HOSPITAL},
        HospitalCheck,
        {"hospital_id": "HOSP9999"},
        {"hospital_id": "HOSP-1257"},
    ),
    "search_policy": (
        {"query": "waiting period for maternity", "product": "Health Secure Plus"},
        RetrievalResult,
        {"query": "waiting period", "product": "No Such Plan"},
        {"query": "   "},
    ),
    "get_coverage": (
        {"product": "Health Secure Plus", "attribute": "maternity"},
        BaseModel,  # CoverageCells; checked by name below
        {"product": "No Such Plan"},
        {"attribute": "colour"},
    ),
}
NEEDS_INDEX = {"search_policy"}


@pytest.fixture
def tool_env(request: pytest.FixtureRequest, warehouse: duckdb.DuckDBPyConnection) -> None:
    """search_policy needs the private index; the others need only the warehouse."""
    if request.node.callspec.params.get("name") in NEEDS_INDEX:
        request.getfixturevalue("index_path")


def _call(name: str, ctx: Any, args: dict[str, Any]) -> Any:
    return TOOLS[name](ctx, **args)


@pytest.mark.parametrize("name", sorted(CASES))
def test_AC_05_01_found(name: str, tool_env: None) -> None:
    found, expected, _, _ = CASES[name]
    result = _call(name, make_ctx(), found)
    assert isinstance(result, expected), result
    if name == "get_coverage":
        assert type(result).__name__ == "CoverageCells" and result.cells


@pytest.mark.parametrize("name", sorted(CASES))
def test_AC_05_01_not_found(name: str, tool_env: None) -> None:
    result = _call(name, make_ctx(), CASES[name][2])
    assert isinstance(result, NotFound), result


@pytest.mark.parametrize("name", sorted(CASES))
def test_AC_05_01_bad_id_format(name: str, tool_env: None) -> None:
    result = _call(name, make_ctx(), CASES[name][3])
    assert isinstance(result, NotFound), result


@pytest.mark.parametrize("name", sorted(CASES))
def test_AC_05_01_access_denied_when_tool_not_listed(
    name: str, tool_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    personas = access.load_personas()
    agent = personas["claims_agent"].model_copy(
        update={"tools": [t for t in personas["claims_agent"].tools if t != name]}
    )
    monkeypatch.setattr(access, "load_personas", lambda: {**personas, "claims_agent": agent})
    assert isinstance(_call(name, make_ctx(), CASES[name][0]), AccessDenied)


OWNED = ["get_claim", "get_claim_documents", "get_claim_interactions", "get_policy", "get_customer_summary"]


@pytest.mark.parametrize("name", OWNED)
def test_AC_05_01_access_denied_for_other_customer(name: str, other_customer: str) -> None:
    ctx = make_ctx("customer", other_customer)
    assert isinstance(_call(name, ctx, CASES[name][0]), AccessDenied)
    # the owner gets the same call through
    assert not isinstance(_call(name, make_ctx("customer", KNOWN_OWNER), CASES[name][0]), AccessDenied)


def test_AC_05_01_customer_name_lookup_denied(warehouse: duckdb.DuckDBPyConnection) -> None:
    result = TOOLS["get_customer_summary"](make_ctx("customer", KNOWN_OWNER), name="Arjun Sharma")
    assert isinstance(result, AccessDenied)


def test_AC_05_01_claim_interactions_found_with_rows(claim_with_interactions: tuple[str, str]) -> None:
    claim_id, _ = claim_with_interactions
    result = TOOLS["get_claim_interactions"](make_ctx(), claim_id=claim_id)
    assert isinstance(result, InteractionHistory)
    assert result.total == len(result.rows) >= 2
    assert sum(result.counts_by_intent.values()) == result.total
    assert result.latest_intent == result.rows[0].intent
    assert [r.interaction_date for r in result.rows] == sorted(
        (r.interaction_date for r in result.rows), reverse=True
    )
    assert "logged_customer_id" not in result.model_dump_json()


def test_AC_05_01_documents_untracked_for_motor(warehouse: duckdb.DuckDBPyConnection) -> None:
    (claim_id,) = warehouse.execute(
        "SELECT claim_id FROM silver.claims WHERE policy_type = 'Motor' ORDER BY claim_id LIMIT 1"
    ).fetchone()  # type: ignore[misc]
    result = TOOLS["get_claim_documents"](make_ctx(), claim_id=claim_id)
    assert isinstance(result, DocumentChecklist)
    assert "Driving licence" in result.untracked
    assert not set(result.untracked) & set(result.missing)
    (gold,) = warehouse.execute(
        "SELECT coalesce(missing_doc_types, []) FROM gold.claim_facts WHERE claim_id = ?", [claim_id]
    ).fetchone()  # type: ignore[misc]
    assert result.missing == list(gold)


@pytest.mark.parametrize("name", sorted(CASES))
def test_AC_05_03_every_success_has_source_matching_guardrails_format(name: str, tool_env: None) -> None:
    result = _call(name, make_ctx(), CASES[name][0])
    assert result.sources
    sql_re, policy_re = sources.label_regexes()
    for ref in result.sources:
        pattern = sql_re if ref.kind == "sql" else policy_re
        assert pattern.fullmatch(ref.label), ref.label


def test_AC_05_03_expected_sql_labels() -> None:
    claim = TOOLS["get_claim"](make_ctx(), claim_id=KNOWN_CLAIM)
    labels = {s.label for s in claim.sources}
    assert {"[claims:CLM300210]", "[policies:POL218917]", "[hospitals:HOSP1257]"} <= labels
    docs = TOOLS["get_claim_documents"](make_ctx(), claim_id=KNOWN_CLAIM)
    assert "[claim_documents:CLM300210]" in {s.label for s in docs.sources}
    inter = TOOLS["get_claim_interactions"](make_ctx(), claim_id=KNOWN_CLAIM)
    assert "[interactions:CLM300210]" in {s.label for s in inter.sources}
    cust = TOOLS["get_customer_summary"](make_ctx(), customer_id=KNOWN_OWNER)
    assert "[customers:CUST139920]" in {s.label for s in cust.sources}


def test_AC_05_04_customer_other_claim_denied(other_customer: str) -> None:
    result = TOOLS["get_claim"](make_ctx("customer", other_customer), claim_id=KNOWN_CLAIM)
    assert isinstance(result, AccessDenied)


def _keys(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from _keys(v)
    elif isinstance(value, list):
        for v in value:
            yield from _keys(v)


def test_AC_05_04_hidden_columns_absent_100_owned_claims(warehouse: duckdb.DuckDBPyConnection) -> None:
    rows = warehouse.execute(
        "SELECT claim_id, customer_id, policy_id, hospital_id FROM silver.claims ORDER BY claim_id"
    ).fetchall()
    calls: list[tuple[str, dict[str, Any]]] = []
    for claim_id, customer_id, policy_id, hospital_id in random.Random(42).sample(rows, 100):
        ctx = make_ctx("customer", customer_id)
        calls = [
            ("get_claim", {"claim_id": claim_id}),
            ("get_claim_documents", {"claim_id": claim_id}),
            ("get_claim_interactions", {"claim_id": claim_id}),
            ("get_policy", {"policy_id": policy_id}),
            ("get_customer_summary", {}),
        ]
        if hospital_id:
            calls.append(("check_hospital", {"hospital_id": hospital_id}))
        for name, args in calls:
            result = TOOLS[name](ctx, **args)
            assert not isinstance(result, (AccessDenied, NotFound)), (name, args, result)
            dumped = result.model_dump(mode="json")
            leaked = set(HIDDEN) & set(_keys(dumped))
            assert not leaked, (name, args, leaked)
            text = json.dumps(dumped)
            assert not any(f'"{h}"' in text for h in HIDDEN)


def test_AC_05_04_hidden_columns_absent_for_owned_claim() -> None:
    """The owner sees no hidden column; an agent sees them on the same claim."""
    result = TOOLS["get_claim"](make_ctx("customer", KNOWN_OWNER), claim_id=KNOWN_CLAIM)
    assert isinstance(result, ClaimView)
    assert not set(HIDDEN) & set(result.model_dump())
    agent = TOOLS["get_claim"](make_ctx("claims_agent"), claim_id=KNOWN_CLAIM)
    assert {"fraud_risk_score", "customer_name"} <= set(agent.model_dump())


def test_AC_05_05_logged_customer_id_only_denied(warehouse: duckdb.DuckDBPyConnection) -> None:
    row = warehouse.execute(
        """SELECT i.claim_id, i.logged_customer_id
           FROM silver.customer_interactions i JOIN silver.claims c USING (claim_id)
           WHERE i.logged_customer_id <> c.customer_id
             AND i.logged_customer_id IN (SELECT customer_id FROM silver.customers)
           ORDER BY i.interaction_id LIMIT 1"""
    ).fetchone()
    assert row is not None
    claim_id, logged = row
    result = TOOLS["get_claim_interactions"](make_ctx("customer", logged), claim_id=claim_id)
    assert isinstance(result, AccessDenied)


@pytest.mark.parametrize("network", ["Network", "Non-Network"])
def test_AC_05_06_alternatives_network_same_city_specialty_not_self(
    network: str, warehouse: duckdb.DuckDBPyConnection
) -> None:
    hospital_id, city, specialty, eligible = warehouse.execute(
        """SELECT h.hospital_id, h.city, h.specialty,
                  (SELECT count(*) FROM silver.hospitals a WHERE a.network_status = 'Network'
                     AND a.city = h.city AND a.specialty = h.specialty
                     AND a.hospital_id <> h.hospital_id) AS n
           FROM silver.hospitals h WHERE h.network_status = ? ORDER BY n DESC, h.hospital_id LIMIT 1""",
        [network],
    ).fetchone()  # type: ignore[misc]
    result = TOOLS["check_hospital"](make_ctx(), hospital_id=hospital_id)
    assert isinstance(result, HospitalCheck) and result.network_status == network
    assert len(result.alternatives) == min(3, eligible) > 0
    for alt in result.alternatives:
        assert alt.network_status == "Network"
        assert (alt.city, alt.specialty) == (city, specialty)
        assert alt.hospital_id != hospital_id


def test_AC_05_07_arjun_sharma_returns_disambiguation(warehouse: duckdb.DuckDBPyConnection) -> None:
    result = TOOLS["get_customer_summary"](make_ctx(), name="Arjun Sharma")
    assert isinstance(result, Disambiguation)
    assert result.entity == "customer" and result.total_matches >= 2
    assert 2 <= len(result.matches) <= 10
    assert all(m.id.startswith("CUST") for m in result.matches)
    (city,) = warehouse.execute(
        """SELECT city FROM gold.v_customer_360 WHERE customer_name = 'Arjun Sharma'
           GROUP BY city HAVING count(*) >= 2 ORDER BY city LIMIT 1"""
    ).fetchone()  # type: ignore[misc]
    narrowed = TOOLS["get_customer_summary"](make_ctx(), name="arjun sharma", city=city)
    assert isinstance(narrowed, Disambiguation)
    assert {m.city for m in narrowed.matches} == {city}


def test_M3_hospital_name_lookup(warehouse: duckdb.DuckDBPyConnection) -> None:
    (name,) = warehouse.execute(
        "SELECT hospital_name FROM silver.hospitals WHERE hospital_id = ?", [KNOWN_HOSPITAL]
    ).fetchone()  # type: ignore[misc]
    result = TOOLS["check_hospital"](make_ctx(), name=name.upper())
    assert isinstance(result, HospitalCheck) and result.hospital_id == KNOWN_HOSPITAL


def test_M3_registry_has_the_eight_spec05_tools() -> None:
    assert set(TOOLS) == set(CASES)
