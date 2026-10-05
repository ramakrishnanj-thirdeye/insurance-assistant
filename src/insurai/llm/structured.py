"""LLM calls with token accounting and an Ollama context-window guard.

`structured_call` validates against a schema with one retry (planner); `text_call` returns plain markdown
(synthesize), which LangGraph streams token by token when the graph runs with stream mode `messages`.
"""

import re
import time
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel

from insurai.llm import Role, get_model
from insurai.observability import get_logger
from insurai.settings import get_settings

log = get_logger(__name__)

CTX_WARN_RATIO = 0.9  # Ollama truncates the prompt silently once it exceeds num_ctx


class StructuredOutputError(RuntimeError):
    """The model returned output that failed schema validation twice."""


class LLMCall(BaseModel):
    role: str
    model: str
    prompt_id: str
    prompt_version: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: float
    attempts: int
    ctx_warning: dict[str, Any] | None = None  # set when input tokens reached 90% of num_ctx


def structured_call[T: BaseModel](
    role: Role,
    schema: type[T],
    messages: list[BaseMessage],
    prompt_id: str,
    prompt_version: str,
    config: RunnableConfig | None = None,
) -> tuple[T, LLMCall]:
    """Call the role model for `schema`; retry once with the validation error, raise on a second failure."""
    model = get_model(role)
    runnable = model.with_structured_output(schema, method="json_schema", include_raw=True)
    cfg: RunnableConfig = {**(config or {}), "tags": [*(config or {}).get("tags", []), f"prompt:{prompt_id}"]}
    start = time.perf_counter()
    tokens_in = tokens_out = 0
    seen_usage = False
    prompt = list(messages)
    raw: Any = None
    for attempt in (1, 2):
        out = runnable.invoke(prompt, config=cfg)
        raw = out.get("raw")
        usage = getattr(raw, "usage_metadata", None)
        if usage:
            seen_usage = True
            tokens_in = max(tokens_in, int(usage.get("input_tokens", 0)))  # retry prompt includes the first
            tokens_out += int(usage.get("output_tokens", 0))
        parsed, error = out.get("parsed"), out.get("parsing_error")
        if parsed is not None and error is None:
            call = LLMCall(
                role=role,
                model=_model_name(model),
                prompt_id=prompt_id,
                prompt_version=prompt_version,
                input_tokens=tokens_in if seen_usage else None,
                output_tokens=tokens_out if seen_usage else None,
                latency_ms=round((time.perf_counter() - start) * 1000, 1),
                attempts=attempt,
                ctx_warning=ctx_warning(role, tokens_in if seen_usage else None),
            )
            if call.ctx_warning:
                log.warning("prompt %s near num_ctx: %s", prompt_id, call.ctx_warning)
            return (parsed if isinstance(parsed, schema) else schema.model_validate(parsed)), call
        log.info("prompt %s attempt %d failed validation: %s", prompt_id, attempt, error)
        prompt = [
            *messages,
            AIMessage(content=str(getattr(raw, "content", "")) or "(no output)"),
            HumanMessage(
                content=f"Your reply failed validation: {error}. "
                "Reply again with only JSON matching the schema."
            ),
        ]
    log.error("prompt %s failed validation twice; giving up", prompt_id)
    raise StructuredOutputError(f"{prompt_id}: output failed {schema.__name__} validation twice")


THINK_BLOCK = re.compile(r"<think>.*?(?:</think>|\Z)", re.DOTALL)


def text_call(
    role: Role,
    messages: list[BaseMessage],
    prompt_id: str,
    prompt_version: str,
    config: RunnableConfig | None = None,
) -> tuple[str, LLMCall]:
    """Call the role model for plain text; a stray `<think>` block is removed from the returned text."""
    model = get_model(role)
    cfg: RunnableConfig = {**(config or {}), "tags": [*(config or {}).get("tags", []), f"prompt:{prompt_id}"]}
    start = time.perf_counter()
    raw = model.invoke(messages, config=cfg)
    usage = getattr(raw, "usage_metadata", None)
    tokens_in = int(usage.get("input_tokens", 0)) if usage else None
    call = LLMCall(
        role=role,
        model=_model_name(model),
        prompt_id=prompt_id,
        prompt_version=prompt_version,
        input_tokens=tokens_in,
        output_tokens=int(usage.get("output_tokens", 0)) if usage else None,
        latency_ms=round((time.perf_counter() - start) * 1000, 1),
        attempts=1,
        ctx_warning=ctx_warning(role, tokens_in),
    )
    if call.ctx_warning:
        log.warning("prompt %s near num_ctx: %s", prompt_id, call.ctx_warning)
    return THINK_BLOCK.sub("", str(raw.content)).strip(), call


def ctx_warning(role: Role, input_tokens: int | None) -> dict[str, Any] | None:
    settings = get_settings()
    spec = settings.llm.profiles[settings.llm.profile][role]
    if spec.provider != "ollama" or spec.num_ctx is None or input_tokens is None:
        return None
    if input_tokens < CTX_WARN_RATIO * spec.num_ctx:
        return None
    return {"input_tokens": input_tokens, "num_ctx": spec.num_ctx, "model": spec.model}


def _model_name(model: BaseChatModel) -> str:
    return str(getattr(model, "model", None) or getattr(model, "model_name", None) or type(model).__name__)
