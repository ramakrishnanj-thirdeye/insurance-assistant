"""Currency check (spec 08): every amount in an answer is in rupees. Any "$" amount or other currency
(config/guardrails.yaml `currency.forbidden_patterns`) fails the check and the draft is retried with
`currency.feedback`. Deterministic; citation labels are removed first so a label can never trip it.
"""

import re
from functools import lru_cache

from insurai.tools.messages import guardrails
from insurai.tools.sources import label_regexes


@lru_cache(maxsize=1)
def _patterns() -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p, re.IGNORECASE) for p in guardrails()["currency"]["forbidden_patterns"])


def currency_hits(text: str) -> list[str]:
    """The non-rupee amounts or currency words in `text`, in order, deduplicated."""
    sql_re, policy_re = label_regexes()
    plain = policy_re.sub(" ", sql_re.sub(" ", text))
    hits = [m.group(0).strip() for p in _patterns() for m in p.finditer(plain)]
    return list(dict.fromkeys(hits))


def currency_feedback() -> str:
    return str(guardrails()["currency"]["feedback"])
