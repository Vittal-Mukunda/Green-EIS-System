"""Exact quantiles with Decimal arithmetic.

Method: linear interpolation between order statistics (Hyndman-Fan type 7, numpy's default
`method="linear"`). For n sorted values x[0..n-1] and probability p = k/m the position is
h = (n-1)*k/m, computed as an exact fraction, and the quantile is
x[floor(h)] + frac(h) * (x[floor(h)+1] - x[floor(h)]). Quantiles are within-sample statistics; with
the study's n = 5 per sector they are coarse (see docs/METHODS.md).
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from gauge.kpi.formula import CONTEXT


def quantile(values: Sequence[Decimal], k: int, m: int) -> Decimal:
    """The k/m quantile of `values` (e.g. k=1, m=4 for P25; k=1, m=3 for the lower tertile cut)."""
    if not values:
        raise ValueError("quantile of an empty sample")
    if not 0 <= k <= m or m <= 0:
        raise ValueError(f"probability {k}/{m} must be within [0, 1]")
    xs = sorted(values)
    n = len(xs)
    numerator = (n - 1) * k
    lower, remainder = divmod(numerator, m)
    if remainder == 0 or lower + 1 >= n:
        return xs[lower]
    step = CONTEXT.divide(
        CONTEXT.multiply(xs[lower + 1] - xs[lower], Decimal(remainder)), Decimal(m)
    )
    return CONTEXT.add(xs[lower], step)


def describe(values: Sequence[Decimal]) -> dict[str, Decimal]:
    """Median, P25, P75 and the two tertile cut-points (probabilities 1/3 and 2/3)."""
    return {
        "median": quantile(values, 1, 2),
        "p25": quantile(values, 1, 4),
        "p75": quantile(values, 3, 4),
        "p33": quantile(values, 1, 3),
        "p67": quantile(values, 2, 3),
    }
