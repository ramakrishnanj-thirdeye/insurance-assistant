"""Identities, scripted plans and SSE parsing shared by the API tests."""

import json
from typing import Any

from fakes import plan_of

AGENT = {"X-Persona": "claims_agent", "X-Principal-Id": "asha"}
SUPERVISOR = {"X-Persona": "supervisor"}  # operator name defaults to staff
OWNER_ID = "CUST139920"  # owns CLM300210
OWNER = {"X-Persona": "customer", "X-Principal-Id": OWNER_ID}
OTHER = {"X-Persona": "customer", "X-Principal-Id": "CUST000001"}

ANALYZE = plan_of(("claim_analysis", {"claim_id": "CLM300210"}), question="Analyze claim CLM300210")
WHY_PENDING = plan_of(("claim_status", {"claim_id": "CLM300210"}), question="Why is CLM300210 pending?")


def parse_sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    """(event, data) pairs from an SSE body; comment and ping lines are skipped."""
    events = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        name, data = None, []
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
        if name:
            events.append((name, json.loads("\n".join(data)) if data else {}))
    return events


def stream(client: Any, path: str, body: dict[str, Any], headers: dict[str, str]) -> Any:
    """POST and return (status, events) for SSE, or (status, problem json) for an error before streaming."""
    response = client.post(path, json=body, headers=headers)
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        return response.status_code, parse_sse(response.text)
    return response.status_code, response.json()
