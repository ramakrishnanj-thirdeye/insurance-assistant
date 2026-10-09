"""Number normalisation for V3 provenance and V6 hidden values (spec 08)."""

import re

# Order matters: dates and IDs first so their digits are not read again as bare numbers.
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_ID = re.compile(r"\b(?:CLM|POL|CUST|HOSP)\d+\b")
_NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")


def number_tokens(text: str) -> set[str]:
    """Normalised numeric tokens: ISO dates, IDs, and numbers with ₹, commas and suffixes stripped.

    Indian and western grouping both normalise (5,00,000 and 500,000 → 500000); 24-month → 24; 12.50 → 12.5.
    """
    tokens: set[str] = set()
    for rx in (_DATE, _ID):
        tokens.update(rx.findall(text))
        text = rx.sub(" ", text)
    for raw in _NUMBER.findall(text):
        if norm := _norm_number(raw):
            tokens.add(norm)
    return tokens


def _norm_number(raw: str) -> str | None:
    digits = raw.replace(",", "").rstrip(".")
    try:
        value = float(digits)
    except ValueError:
        return None
    return str(int(value)) if value == int(value) else repr(value)
