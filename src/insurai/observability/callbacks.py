"""LangChain callback that records every chat-model call: count, tags and prompt message types.

Pass it in the graph config (`{"callbacks": [recorder]}`); child runnables inherit it, so a node's LLM
calls are counted without the node knowing about it (AC-06-05, AC-06-12).
"""

from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from pydantic import BaseModel


class RecordedCall(BaseModel):
    tags: list[str]
    message_types: list[str]  # "system", "human", "ai", ... in prompt order

    def count(self, kind: str) -> int:
        return self.message_types.count(kind)


class LLMCallRecorder(BaseCallbackHandler):
    def __init__(self) -> None:
        self.calls: list[RecordedCall] = []

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        for prompt in messages:
            self.calls.append(RecordedCall(tags=list(tags or []), message_types=[m.type for m in prompt]))

    def tagged(self, tag: str) -> list[RecordedCall]:
        return [c for c in self.calls if tag in c.tags]
