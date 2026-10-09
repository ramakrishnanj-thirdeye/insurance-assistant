"""Proportions with counts and 95% Wilson score intervals (spec 11 reports).

A slice reports each proportion twice: the float in `metrics` (what the gate and the dashboard read) and
`[k, n]` in `counts`, from which the markdown report renders "10 of 15, 0.42–0.85".
"""

import math
from collections.abc import Iterable
from typing import Any

Z95 = 1.959964
SMALL_N = 30  # below this a ratio alone misleads: the report always shows counts and the interval


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """95% Wilson score interval for k successes in n trials; (0, 1) when n is 0."""
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return round(max(0.0, centre - half), 6), round(min(1.0, centre + half), 6)


def ratio(k: int, n: int) -> float | None:
    return round(k / n, 4) if n else None


def count(values: Iterable[Any]) -> tuple[int, int]:
    """(truthy, total) over values, None values skipped."""
    seen = [bool(v) for v in values if v is not None]
    return sum(seen), len(seen)


def prop(metrics: dict[str, Any], counts: dict[str, list[int]], name: str, k: int, n: int) -> None:
    """Record one proportion in both places."""
    metrics[name] = ratio(k, n)
    counts[name] = [k, n]


def fmt_prop(k: int, n: int) -> str:
    """ "10 of 15, 0.42–0.85" (n < 30) or "0.9667 (58 of 60, 0.89–0.99)"."""
    if n == 0:
        return "n = 0"
    lo, hi = wilson(k, n)
    if n < SMALL_N:
        return f"{k} of {n}, {lo:.2f}–{hi:.2f}"
    return f"{k / n:.4f} ({k} of {n}, {lo:.2f}–{hi:.2f})"
