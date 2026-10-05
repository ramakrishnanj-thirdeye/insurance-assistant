"""Scripted chat model for agent unit tests: no network, scripted structured outputs, real callbacks.

Responses are keyed by the structured-output schema name ("Plan"), or "Text" for plain calls (synthesize).
Each value is a list (consumed in order) or a callable taking the prompt messages. A str response is
returned verbatim, so a test can script invalid JSON. Plain calls stream word by word when the caller
streams (LangGraph stream mode `messages`), so tests see real token events.
"""

import json
import re
from collections.abc import Callable, Iterator, Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel, ValidationError

Responder = list[Any] | Callable[[list[BaseMessage]], Any]


class ScriptedChatModel(BaseChatModel):
    responses: dict[str, Any]
    model: str = "scripted-fake"
    input_tokens: int = 120
    output_tokens: int = 30

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        schema_name: str | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        message = AIMessage(content=self._content(messages, schema_name), usage_metadata=self._usage())
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        schema_name: str | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        pieces = re.findall(r"\S+\s*|\s+", self._content(messages, schema_name)) or [""]
        for n, piece in enumerate(pieces, start=1):
            usage = self._usage() if n == len(pieces) else None
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=piece, usage_metadata=usage))
            if run_manager:
                run_manager.on_llm_new_token(piece, chunk=chunk)
            yield chunk

    def _content(self, messages: list[BaseMessage], schema_name: str | None) -> str:
        script = self.responses[schema_name or "Text"]
        value = script(messages) if callable(script) else script.pop(0)
        if isinstance(value, BaseModel):
            return value.model_dump_json()
        return value if isinstance(value, str) else json.dumps(value)

    def _usage(self) -> Any:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.input_tokens + self.output_tokens,
        }

    def with_structured_output(  # type: ignore[override]
        self, schema: Any, *, include_raw: bool = False, **kwargs: Any
    ) -> Runnable:
        def parse(message: AIMessage) -> dict[str, Any]:
            try:
                return {
                    "raw": message,
                    "parsed": schema.model_validate_json(message.content),
                    "parsing_error": None,
                }
            except ValidationError as exc:
                return {"raw": message, "parsed": None, "parsing_error": exc}

        return self.bind(schema_name=schema.__name__) | RunnableLambda(parse)


def install(monkeypatch: Any, responses: dict[str, Responder], **kwargs: Any) -> ScriptedChatModel:
    """Route every LLM call (structured and plain) to one scripted model."""
    from insurai.llm import structured

    model = ScriptedChatModel(responses=responses, **kwargs)
    monkeypatch.setattr(structured, "get_model", lambda role: model)
    return model


def forbid_llm(monkeypatch: Any) -> None:
    from insurai.llm import structured

    def _fail(role: str) -> None:
        raise AssertionError(f"LLM call attempted (role {role})")

    monkeypatch.setattr(structured, "get_model", _fail)


def history_turns(message_types: Sequence[str]) -> int:
    """Completed user+assistant turns in a prompt, excluding the system message and the current question."""
    body = [t for t in message_types if t != "system"]
    if body and body[-1] == "human":
        body = body[:-1]
    return sum(1 for t in body if t == "human")


# --- scripted planner and synthesizer --------------------------------------------------------------------


def plan_of(*intents: tuple[str, dict[str, str]], question: str = "q") -> Any:
    from insurai.agent.schemas import Entities, Intent, Plan

    return Plan(
        intents=[
            Intent(id=f"i{n}", type=t, entities=Entities(**e), sub_question=question)
            for n, (t, e) in enumerate(intents, start=1)
        ]
    )


def planner_script(table: dict[str, Any]) -> Callable[[list[BaseMessage]], Any]:
    """Answer the planner by substring of the current question (the last prompt message)."""

    def reply(messages: list[BaseMessage]) -> Any:
        question = str(messages[-1].content).lower()
        for key, plan in table.items():
            if key.lower() in question:
                return plan
        raise AssertionError(f"no scripted plan for {question!r}")

    return reply


def citing_synth(messages: list[BaseMessage]) -> Any:
    """A synthesizer that cites the first evidence label it was given and states no numbers."""
    from insurai.guardrails.verify import labels_in

    labels = [
        label
        for attr in re.findall(r'source="([^"]*)"', str(messages[0].content))
        for label in labels_in(attr)
    ]
    first = labels[0] if labels else ""
    return f"Here is what the records show. {first}".strip()
