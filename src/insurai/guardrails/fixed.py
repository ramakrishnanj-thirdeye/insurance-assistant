"""Fixed system sentences (spec 08): each appears only where its trigger applies, and at most once.

- the precedence sentence (config/guardrails.yaml `conflict_rendering`) only when `find_conflicts` reports a
  schedule/wording conflict;
- the mandated wording (`no_guarantee.mandated_wording`) only on a guarantee request, after a V4 rewrite, or
  in the customer specialist-review block that `respond` appends.

Models copy both from the prompt rules into answers that have no trigger (EVAL032 carried the precedence
sentence without a conflict); `strip_untriggered` removes those copies deterministically, sentence by
sentence, keeping each line's other sentences and the answer's line structure.
"""

import re

from insurai.guardrails.verify import strip_labels
from insurai.tools.messages import guardrails

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_LINE_MARKER = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_MARKDOWN = re.compile(r"[*_`#>]+")


def _norm(text: str) -> str:
    plain = _MARKDOWN.sub(" ", strip_labels(_LINE_MARKER.sub("", text))).casefold()
    return " ".join(plain.split()).strip(" .:;,!?")


def precedence_sentence() -> str:
    return str(guardrails()["conflict_rendering"]["precedence_sentence"])


def mandated_wording() -> str:
    return str(guardrails()["no_guarantee"]["mandated_wording"])


def drop_sentence(text: str, sentence: str, keep_first: bool = False) -> str:
    """`text` without `sentence` (compared without labels, markdown, list markers or final punctuation);
    with `keep_first`, only repeats are removed. A line left empty is removed; paragraphs stay apart."""
    target = _norm(sentence)
    seen = False
    lines: list[str] = []
    changed = False
    for line in text.split("\n"):
        parts = _SENTENCE_END.split(line)
        kept: list[str] = []
        for part in parts:
            if _norm(part) == target:
                if keep_first and not seen:
                    seen = True
                    kept.append(part)
                else:
                    changed = True
                continue
            kept.append(part)
        if len(kept) == len(parts):
            lines.append(line)
        elif any(_norm(p) for p in kept):
            lines.append(" ".join(kept))
    if not changed:
        return text
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def strip_untriggered(text: str, *, conflict: bool, mandated_allowed: bool) -> str:
    """Remove the precedence sentence without a conflict and the mandated wording without its trigger; where
    allowed, keep each once."""
    text = drop_sentence(text, precedence_sentence(), keep_first=conflict)
    return drop_sentence(text, mandated_wording(), keep_first=mandated_allowed)


def mandated_once(text: str) -> str:
    """The mandated wording at most once (a guarantee lead and the specialist-review block both carry it)."""
    return drop_sentence(text, mandated_wording(), keep_first=True)
