"""Friendly status line (spec 10): phrases from config/ui_status.yaml, chosen per event. Pure, unit-tested.

A node's phrases rotate on each `heartbeat`; a tool's line names the record from status-safe arguments
only; after the planner, "Understood: …" summarises the plan. The customer persona always gets the
default (professional) tone.
"""

import string
from functools import lru_cache
from typing import Any

import yaml
from pydantic import BaseModel, Field

from insurai.observability.progress import status_args
from insurai.settings import ROOT

STATUS_FILE = ROOT / "config" / "ui_status.yaml"
SAFE_PLACEHOLDERS = frozenset({"claim_id", "policy_id", "product", "hospital_id"})
UNDERSTOOD_PLACEHOLDERS = SAFE_PLACEHOLDERS | {"intents"}
PLAN_NODES = ("planner", "resolve_context")


class Tone(BaseModel):
    nodes: dict[str, list[str]]
    tools: dict[str, list[str]]
    understood: list[str]
    badges: dict[str, str]


class TraceLabels(BaseModel):
    """Past-tense step labels for the client-friendly trace view (AC-10-12)."""

    nodes: dict[str, list[str]] = Field(default_factory=dict)
    entity: list[str] = Field(default_factory=list)
    intent: list[str] = Field(default_factory=list)
    tools: dict[str, list[str]] = Field(default_factory=dict)
    retrieval: list[str] = Field(default_factory=list)
    llm: dict[str, list[str]] = Field(default_factory=dict)
    verify: list[str] = Field(default_factory=list)
    warnings: dict[str, list[str]] = Field(default_factory=dict)


class StatusConfig(BaseModel):
    version: int
    default_tone: str
    tones: dict[str, Tone]
    intent_labels: dict[str, str] = Field(default_factory=dict)
    trace_labels: TraceLabels = Field(default_factory=TraceLabels)


@lru_cache(maxsize=1)
def load_status() -> StatusConfig:
    return StatusConfig.model_validate(yaml.safe_load(STATUS_FILE.read_text(encoding="utf-8")))


def tone_names() -> list[str]:
    return list(load_status().tones)


def select_tone(persona: str, requested: str | None) -> str:
    """The customer persona always gets the default tone; other personas may pick any configured tone."""
    cfg = load_status()
    if persona == "customer" or requested not in cfg.tones:
        return cfg.default_tone
    return str(requested)


def placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def fill_first(templates: list[str], values: dict[str, Any]) -> str | None:
    """The first template whose placeholders all have values."""
    for template in templates:
        names = placeholders(template)
        if all(values.get(n) for n in names):
            return template.format(**{n: values[n] for n in names})
    return None


def status_line(event: str, data: dict[str, Any], tone: str) -> str | None:
    """The status text for one SSE event, or None to keep the current line."""
    phrases = load_status().tones[tone]
    if event == "node" and data.get("status") == "start":
        return _rotate(phrases.nodes.get(str(data.get("name"))), 0)
    if event == "heartbeat":
        return _rotate(phrases.nodes.get(str(data.get("node"))), int(data.get("beat", 0)))
    if event == "tool_start":
        args = status_args(data.get("args_redacted") or {})  # re-checked here: IDs and product names only
        return fill_first(phrases.tools.get(str(data.get("name")), []), args)
    if event == "node" and data.get("name") in PLAN_NODES and isinstance(data.get("plan"), dict):
        return understood(data["plan"], tone)
    return None


def understood(plan: dict[str, Any], tone: str) -> str | None:
    """The plan summary as a line, e.g. Understood: policy question · Health Secure Plus."""
    cfg = load_status()
    labels = [cfg.intent_labels.get(t, t.replace("_", " ")) for t in plan.get("intents", [])]
    if not labels:
        return None
    first = {
        "product": plan.get("product"),
        "claim_id": next(iter(plan.get("claim_ids") or []), None),
        "policy_id": next(iter(plan.get("policy_ids") or []), None),
    }
    values = {"intents": " + ".join(labels), **status_args(first)}
    return fill_first(cfg.tones[tone].understood, values)


def badge(phase: str, tone: str) -> str | None:
    """The draft badge: checking… while drafting or checking, revising…, ✓ verified; none otherwise."""
    badges = load_status().tones[tone].badges
    key = {"drafting": "checking", "checking": "checking", "revising": "revising", "verified": "verified"}
    return badges[key[phase]] if phase in key else None


def _rotate(items: list[str] | None, beat: int) -> str | None:
    return items[beat % len(items)] if items else None
