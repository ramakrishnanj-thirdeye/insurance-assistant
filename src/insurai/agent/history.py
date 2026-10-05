"""History window (spec 06 Memory): the last N user+assistant turns; earlier tool or evidence messages
are never replayed.
"""

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, trim_messages


def window(messages: list[BaseMessage], turns: int) -> list[BaseMessage]:
    """The last `turns` completed turns before the current question (which is excluded).

    A turn is a user message plus the assistant reply; the window starts on a user message.
    """
    convo = [m for m in messages if isinstance(m, HumanMessage | AIMessage)]
    if convo and isinstance(convo[-1], HumanMessage):
        convo = convo[:-1]  # the current question goes into the prompt separately
    if turns <= 0 or not convo:
        return []
    return trim_messages(
        convo,
        max_tokens=turns,
        token_counter=lambda msgs: sum(isinstance(m, HumanMessage) for m in msgs),
        strategy="last",
        start_on="human",
        allow_partial=False,
    )
