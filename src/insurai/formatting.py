"""Display formatting shared by tools, the synthesizer and the UI."""

from decimal import ROUND_HALF_UP, Decimal


def inr(amount: int | float | Decimal, decimals: int = 0) -> str:
    """Indian rupees with lakh/crore grouping: ``inr(500000) == "₹5,00,000"``."""
    quantum = Decimal(1).scaleb(-decimals)
    value = Decimal(str(amount)).quantize(quantum, rounding=ROUND_HALF_UP)
    sign = "-" if value < 0 else ""
    whole, _, fraction = f"{abs(value):f}".partition(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while head:
        groups.insert(0, head[-2:])
        head = head[:-2]
    grouped = ",".join([*groups, tail])
    return f"{sign}₹{grouped}" + (f".{fraction}" if fraction else "")
