"""V6 hidden fields (spec 08 Output layer): a customer-persona answer may not mention the fraud score, the
manual review flag or the risk segment, nor show their values.

Terms come from config/guardrails.yaml `hidden_field_terms`. Values come from the warehouse for the
customer in session (`lookup_hidden`): their claims' fraud scores (V3-normalised, also rounded to 2 dp)
and their risk segment, which fails only next to a segment word or after "risk:" ("High" alone is ordinary
English, and the wordings say "High-risk adventure activities").
"""

import re
from functools import lru_cache

from insurai.guardrails.numbers import number_tokens
from insurai.guardrails.schemas import HiddenValues
from insurai.tools.base import fetch_all, fetch_one
from insurai.tools.messages import guardrails

_SEGMENT_WORDS = (
    r"(?:segment|category|profile|tier|band)"  # not "risk": "High-risk adventure activities" is wording
)


@lru_cache(maxsize=1)
def _terms() -> list[re.Pattern[str]]:
    return [re.compile(p, re.IGNORECASE) for p in guardrails()["hidden_field_terms"]]


def hidden_hits(answer: str, hidden: HiddenValues | None = None) -> list[str]:
    """What the answer reveals: matched terms (lower case), "fraud score value", "risk segment value"."""
    hits = list(dict.fromkeys(m.group(0).lower() for rx in _terms() if (m := rx.search(answer))))
    if hidden is None:
        return hits
    if number_tokens(answer) & hidden.fraud_scores:
        hits.append("fraud score value")
    for segment in hidden.segments:
        seg = re.escape(segment)
        near = (
            rf"\b{seg}\b\W+(?:\w+\W+){{0,2}}?{_SEGMENT_WORDS}\b"
            rf"|\b{_SEGMENT_WORDS}\W+(?:\w+\W+){{0,2}}?{seg}\b"
            rf"|\brisk\s*[:=]\s*{seg}\b"
        )
        if re.search(near, answer, re.IGNORECASE):
            hits.append("risk segment value")
            break
    return hits


def lookup_hidden(principal_id: str) -> HiddenValues:
    """The hidden values of `principal_id`'s claims and customer record (parameterised, read-only)."""
    scores: set[str] = set()
    rows = fetch_all(
        "SELECT fraud_risk_score FROM gold.v_claim_360 "
        "WHERE customer_id = ? AND fraud_risk_score IS NOT NULL",
        [principal_id],
    )
    for row in rows:
        value = float(row["fraud_risk_score"])
        scores |= number_tokens(str(value)) | number_tokens(f"{value:.2f}")
    customer = fetch_one("SELECT risk_segment FROM silver.customers WHERE customer_id = ?", [principal_id])
    segments = {str(customer["risk_segment"])} if customer and customer.get("risk_segment") else set()
    return HiddenValues(fraud_scores=scores, segments=segments)
