"""TraceEvent helpers (spec 06 Trace)."""

import time
from typing import Any

from insurai.agent.schemas import TraceEvent, TraceKind
from insurai.llm.structured import LLMCall


def now_ms() -> float:
    return time.time() * 1000


def event(kind: TraceKind, name: str, turn: int, start_ms: float, **data: Any) -> TraceEvent:
    return TraceEvent(kind=kind, name=name, turn=turn, start_ms=start_ms, end_ms=now_ms(), data=data)


def instant(kind: TraceKind, name: str, turn: int, **data: Any) -> TraceEvent:
    t = now_ms()
    return TraceEvent(kind=kind, name=name, turn=turn, start_ms=t, end_ms=t, data=data)


def llm_events(call: LLMCall, turn: int, start_ms: float) -> list[TraceEvent]:
    """The llm event (role, model, tokens, latency), the prompt id/version, and a num_ctx warning if any."""
    events = [
        event("llm", call.prompt_id, turn, start_ms, **call.model_dump(exclude={"ctx_warning"})),
        instant("prompt", call.prompt_id, turn, prompt_id=call.prompt_id, version=call.prompt_version),
    ]
    if call.ctx_warning:
        events.append(
            instant("warning", "ctx_near_limit", turn, prompt_id=call.prompt_id, **call.ctx_warning)
        )
    return events
