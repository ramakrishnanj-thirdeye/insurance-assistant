"""Streaming safety and status payloads (spec 09): the per-attempt draft gate and the plan summary.

Never stream a promise: the V4 no-guarantee patterns run on each attempt's accumulated draft. Text is
released only once it is `holdback_chars()` behind the newest token (and on a word boundary), so a
phrase split across chunks is never partly sent. On a hit the attempt goes quiet and one `draft_hidden`
event says so; the verified final answer carries the mandated wording. `<think>` blocks never stream.
"""

import re
import re._parser as parser  # stdlib regex parser: a pattern's maximum match width
from re._constants import MAXREPEAT
from typing import Any

from insurai.agent.schemas import Plan
from insurai.guardrails.verify import guarantee_hits
from insurai.observability.progress import status_args
from insurai.tools.messages import guardrails

THINK_OPEN, THINK_CLOSE = "<think>", "</think>"


def holdback_for(patterns: list[str], margin: int, cap: int) -> int:
    """The longest possible match over `patterns` plus `margin`; `cap` when a pattern is unbounded."""
    widths = [parser.parse(p, re.IGNORECASE).getwidth()[1] for p in patterns]
    longest = max(widths, default=0)
    return cap if longest >= MAXREPEAT else min(cap, longest + margin)


def holdback_chars() -> int:
    cfg = guardrails()["no_guarantee"]
    return holdback_for(cfg["patterns"], int(cfg["stream_holdback_margin"]), int(cfg["stream_holdback_max"]))


def visible_text(text: str) -> tuple[str, bool]:
    """The draft without `<think>` blocks, and whether a block is still open at the end."""
    out: list[str] = []
    i = 0
    while (j := text.find(THINK_OPEN, i)) >= 0:
        out.append(text[i:j])
        k = text.find(THINK_CLOSE, j)
        if k < 0:
            return "".join(out), True
        i = k + len(THINK_CLOSE)
    out.append(text[i:])
    return "".join(out), False


class DraftGate:
    """One synthesize attempt's token stream: yields safe `token` text or a single `draft_hidden`."""

    def __init__(self, attempt: int, holdback: int | None = None) -> None:
        self.attempt = attempt
        self.holdback = holdback_chars() if holdback is None else holdback
        self.raw = ""
        self.released = 0
        self.hidden: str | None = None

    def feed(self, chunk: str) -> list[tuple[str, dict[str, Any]]]:
        if self.hidden is not None or not chunk:
            return []
        self.raw += chunk
        visible, _ = visible_text(self.raw)
        if guarantee_hits(visible):
            return self._hide("guarantee")
        limit = len(visible) - self.holdback
        if limit <= self.released:  # a negative limit would count from the end in rfind
            return []
        cut = max(visible.rfind(" ", self.released, limit), visible.rfind("\n", self.released, limit))
        if cut < self.released:
            return []
        return self._release(visible, cut + 1)

    def close(self) -> list[tuple[str, dict[str, Any]]]:
        """The attempt ended: release the held tail, or hide the attempt."""
        if self.hidden is not None:
            return []
        visible, open_think = visible_text(self.raw)
        if open_think:
            return self._hide("reasoning")
        if guarantee_hits(visible):
            return self._hide("guarantee")
        return self._release(visible, len(visible))

    def _release(self, visible: str, end: int) -> list[tuple[str, dict[str, Any]]]:
        text, self.released = visible[self.released : end], max(self.released, end)
        return [("token", {"text": text, "attempt": self.attempt})] if text else []

    def _hide(self, reason: str) -> list[tuple[str, dict[str, Any]]]:
        self.hidden = reason
        return [("draft_hidden", {"attempt": self.attempt, "reason": reason})]


def plan_summary(plan: Plan | None) -> dict[str, Any]:
    """Intent types, product, claim and policy IDs: nothing a user typed as free text, no customer data."""
    intents = plan.intents if plan is not None else []
    products = [p for i in intents if (p := status_args({"product": i.entities.product}).get("product"))]
    return {
        "intents": list(dict.fromkeys(i.type for i in intents)),
        "product": products[0] if products else None,
        "claim_ids": _ids(intents, "claim_id"),
        "policy_ids": _ids(intents, "policy_id"),
    }


def _ids(intents: list[Any], field: str) -> list[str]:
    values = (status_args({field: getattr(i.entities, field)}).get(field) for i in intents)
    return list(dict.fromkeys(v for v in values if v))
