"""Client-friendly trace (spec 10, AC-10-12): plain steps, named verifier checks, evidence tables. Pure.

Step labels come from `trace_labels` in config/ui_status.yaml and check names from `check_names` in
config/guardrails.yaml. Placeholders are filled from status-safe values only (`status_args`), so a step never
shows a customer name. The raw events stay available under "Engineer details".
"""

from typing import Any

from status import fill_first, load_status
from views import duration_ms

from insurai.observability.progress import status_args
from insurai.tools.messages import guardrails

Event = dict[str, Any]
V7_EVAL_ONLY = "runs in the eval only"  # the tail of agent.graph.V7_OFF_NOTE
LLM_ANSWER = "language model"
NO_LLM = "template (no LLM)"
ANSWERED_BY = {"refusal": "fixed refusal (no LLM)", "clarification": "clarifying question"}


def _safe(data: dict[str, Any]) -> dict[str, str]:
    return status_args({**data, **(data.get("args") or {})})


def intent_types(data: dict[str, Any]) -> list[str]:
    """Intent types of an intent event: {"id", "type", "entities"} rows; plain strings in older traces."""
    rows = data.get("intents") or []
    return [str(r.get("type", "")) if isinstance(r, dict) else str(r) for r in rows]


def step_label(ev: Event) -> str | None:
    """The plain-language step for one trace event, or None for events shown only to engineers."""
    labels = load_status().trace_labels
    kind, name, data = ev.get("kind"), str(ev.get("name", "")), ev.get("data") or {}
    match kind:
        case "node":
            values = {"n": data.get("rules"), "action": data.get("action")}
            return fill_first(labels.nodes.get(name, []), values)
        case "entity":
            return fill_first(labels.entity, {})
        case "intent":
            intent_labels = load_status().intent_labels
            intents = " + ".join(intent_labels.get(t, t.replace("_", " ")) for t in intent_types(data))
            return fill_first(labels.intent, {"intents": intents})
        case "tool":
            return fill_first(labels.tools.get(name, []), _safe(data))
        case "retrieval":
            return fill_first(labels.retrieval, {"n": len(data.get("chunks") or []) or None})
        case "llm":
            return fill_first(labels.llm.get(name) or labels.llm.get("default", []), {})
        case "verify":
            return fill_first(labels.verify, {})
        case "warning":
            return fill_first(labels.warnings.get(name) or labels.warnings.get("default", []), {})
    return None


def _outcome(ev: Event) -> str:
    data = ev.get("data") or {}
    if ev.get("kind") == "node" and ev.get("name") == "input_guard":
        return "passed" if data.get("allowed", True) else f"blocked ({data.get('code')})"
    if ev.get("kind") == "verify":
        return {"pass": "passed", "retry": "asked for a revision", "abstain": "not confident: abstained"}.get(
            str(data.get("outcome")), str(data.get("outcome", ""))
        )
    if ev.get("kind") == "tool" and data.get("result_kind") not in (None, "ok"):
        return str(data["result_kind"]).replace("_", " ")
    if ev.get("kind") == "retrieval":
        return "confident" if data.get("confident") else "no confident match"
    return ""


def step_rows(trace: list[Event]) -> list[dict[str, Any]]:
    rows = []
    for ev in sorted(trace, key=lambda e: float(e.get("start_ms", 0))):
        if (label := step_label(ev)) is not None:
            rows.append({"step": label, "result": _outcome(ev), "ms": duration_ms(ev)})
    return rows


def answered_by_label(trace: list[Event]) -> str | None:
    """Who wrote the answer: "language model", "template (no LLM)", a refusal or a clarifying question."""
    total = next((e for e in reversed(trace) if e.get("kind") == "total"), None)
    if total is None:
        return None
    data = total.get("data") or {}
    by = str(data.get("answered_by", ""))
    if by.startswith("guard:"):
        return "safety check (no LLM)"
    if by in ANSWERED_BY:
        return ANSWERED_BY[by]
    written = data.get("llm_written")
    if written is None:  # traces written before llm_written existed
        written = by == "draft" and any(
            e.get("kind") == "llm" and e.get("name") in ("synthesize", "dossier_narrative") for e in trace
        )
    return LLM_ANSWER if written else NO_LLM


def check_name(check: str) -> str:
    names: dict[str, str] = guardrails().get("check_names", {})
    return f"{check} {names[check]}" if check in names else check


def check_rows(trace: list[Event]) -> list[dict[str, str]]:
    """The last verify attempt's checks, named, with the detail on a failure or a skip."""
    verify = [e for e in trace if e.get("kind") == "verify"]
    if not verify:
        return []
    rows = []
    for c in (verify[-1].get("data") or {}).get("checks", []):
        detail = str(c.get("detail") or "")
        if c.get("skipped"):
            result = "skipped (eval only)" if V7_EVAL_ONLY in detail else "skipped"
            detail = "" if V7_EVAL_ONLY in detail else detail
        elif c.get("passed"):
            result, detail = "✓ passed", ""
        else:
            result = "✗ failed"
        rows.append({"check": check_name(str(c.get("check"))), "result": result, "detail": detail})
    return rows


def verify_attempts(trace: list[Event]) -> int:
    return sum(1 for e in trace if e.get("kind") == "verify")


def chunk_rows(trace: list[Event]) -> list[dict[str, Any]]:
    return [
        {
            "label": c.get("label"),
            "fused rank": c.get("fused_rank"),
            "rerank score": c.get("rerank_score"),
            "via": c.get("via"),
        }
        for e in trace
        if e.get("kind") == "retrieval"
        for c in (e.get("data") or {}).get("chunks", [])
    ]


def rule_rows(trace: list[Event]) -> list[dict[str, Any]]:
    return [
        {"rule": e.get("name"), "status": e["data"].get("status"), "severity": e["data"].get("severity")}
        for e in trace
        if e.get("kind") == "rule" and isinstance(e.get("data"), dict)
    ]


def llm_rows(trace: list[Event]) -> list[dict[str, Any]]:
    versions = {
        e.get("name"): (e.get("data") or {}).get("version") for e in trace if e.get("kind") == "prompt"
    }
    rows = []
    for e in trace:
        if e.get("kind") != "llm":
            continue
        d = e.get("data") or {}
        rows.append(
            {
                "prompt": d.get("prompt_id", e.get("name")),
                "version": d.get("prompt_version") or versions.get(e.get("name")),
                "model": d.get("model"),
                "role": d.get("role"),
                "tokens in": d.get("input_tokens"),
                "tokens out": d.get("output_tokens"),
                "latency ms": d.get("latency_ms"),
            }
        )
    return rows


def sql_blocks(trace: list[Event]) -> list[tuple[str, str]]:
    return [
        (str(e.get("name")), e["data"]["sql"])
        for e in trace
        if isinstance(e.get("data"), dict) and isinstance(e["data"].get("sql"), str)
    ]
