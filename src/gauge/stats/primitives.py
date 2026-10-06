"""Small, separately tested statistical building blocks (spec §5).

Everything here is deterministic given its inputs (the bootstrap takes a seed). Functions return NaN,
never raise, when a statistic is undefined (for example agreement among raters who all gave the same
single value), and say so through their return value, so one degenerate cell cannot stop a report.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
from scipy import stats as sps

NAN = float("nan")


# ---- agreement ---------------------------------------------------------------------------
def disagreement_matrix(k: int, weights: str | None) -> np.ndarray:
    """k x k disagreement weights: 0/1 (nominal), |i-j|/(k-1) (linear) or its square (quadratic)."""
    i, j = np.indices((k, k))
    if weights is None:
        return (i != j).astype(float)
    if weights == "linear":
        return np.abs(i - j) / max(k - 1, 1)
    if weights == "quadratic":
        return ((i - j) / max(k - 1, 1)) ** 2
    raise ValueError(f"unknown weights {weights!r}")


def kappa_from_codes(a: np.ndarray, b: np.ndarray, disagreement: np.ndarray) -> float:
    """Cohen's kappa for integer category codes 0..k-1 (the fast path used inside bootstraps)."""
    k = disagreement.shape[0]
    if a.size == 0:
        return NAN
    observed = np.bincount(a * k + b, minlength=k * k).reshape(k, k) / a.size
    expected = np.outer(observed.sum(axis=1), observed.sum(axis=0))
    d_expected = float((disagreement * expected).sum())
    if d_expected == 0:
        return NAN
    return 1.0 - float((disagreement * observed).sum()) / d_expected


def cohen_kappa(
    a: Sequence, b: Sequence, *, weights: str | None = None, labels: Sequence | None = None
) -> float:
    """Cohen's kappa for two ratings of the same items.

    weights: None (nominal), "linear" or "quadratic" (ordinal; `labels` must then be ordered).
    `labels` fixes the category set (and, for weighted kappa, the order and spacing); by default the
    sorted union of the values seen. NaN when chance agreement is perfect (both raters used one
    single category), where kappa is undefined.
    """
    if len(a) != len(b):
        raise ValueError("the two ratings must have the same length")
    if len(a) == 0:
        return NAN
    cats = list(labels) if labels is not None else sorted(set(a) | set(b))
    index = {c: i for i, c in enumerate(cats)}
    codes_a = np.array([index[x] for x in a], dtype=np.intp)
    codes_b = np.array([index[y] for y in b], dtype=np.intp)
    return kappa_from_codes(codes_a, codes_b, disagreement_matrix(len(cats), weights))


def fleiss_kappa(table: np.ndarray) -> float:
    """Fleiss' kappa. `table` is items x categories, each cell the number of raters who put the item
    in that category; every item must have the same number of raters (at least 2)."""
    table = np.asarray(table, dtype=float)
    n_items, _ = table.shape
    n = table[0].sum()
    if not np.all(table.sum(axis=1) == n) or n < 2:
        raise ValueError("every item needs the same number (>= 2) of ratings")
    p_item = ((table**2).sum(axis=1) - n) / (n * (n - 1))
    p_bar = p_item.mean()
    p_cat = table.sum(axis=0) / (n_items * n)
    p_e = float((p_cat**2).sum())
    if p_e == 1.0:
        return NAN
    return float((p_bar - p_e) / (1 - p_e))


def krippendorff_alpha(data: np.ndarray, level: str) -> float:
    """Krippendorff's alpha for `data` (raters x units, NaN = missing), level of measurement
    "nominal" or "ordinal". NaN when undefined (no variation, or no unit rated twice)."""
    import krippendorff

    data = np.asarray(data, dtype=float)
    try:
        value = krippendorff.alpha(reliability_data=data, level_of_measurement=level)
    except ValueError:
        return NAN
    return float(value) if np.isfinite(value) else NAN


# ---- proportions and tests ---------------------------------------------------------------
def clopper_pearson(k: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Exact binomial confidence interval for a proportion k/n."""
    if n <= 0:
        return (NAN, NAN)
    a = (1 - confidence) / 2
    low = 0.0 if k == 0 else float(sps.beta.ppf(a, k, n - k + 1))
    high = 1.0 if k == n else float(sps.beta.ppf(1 - a, k + 1, n - k))
    return low, high


def exact_mcnemar(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value from the two discordant counts (b, c)."""
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, 2.0 * float(sps.binom.cdf(min(b, c), n, 0.5)))


def paired_odds_ratio(b: int, c: int, confidence: float = 0.95) -> tuple[float, float, float]:
    """Conditional odds ratio b/c of the discordant pairs, with an exact confidence interval from
    the Clopper-Pearson interval of b/(b+c). Returns (or, low, high); infinite or NaN if undefined."""
    n = b + c
    if n == 0:
        return (NAN, NAN, NAN)
    low_p, high_p = clopper_pearson(b, n, confidence)

    def to_or(p: float) -> float:
        return math.inf if p >= 1 else p / (1 - p)

    estimate = math.inf if c == 0 and b > 0 else (b / c if c else NAN)
    return estimate, to_or(low_p), to_or(high_p)


def binomial_greater(k: int, n: int, p0: float = 0.5) -> float:
    """One-sided exact binomial p-value for H1: success probability > p0."""
    if n == 0:
        return NAN
    return float(sps.binomtest(k, n, p0, alternative="greater").pvalue)


def holm(pvalues: Sequence[float]) -> list[float]:
    """Holm-Bonferroni adjusted p-values, in the input order (NaNs are left out of the family)."""
    p = np.asarray(pvalues, dtype=float)
    out = np.full(p.shape, np.nan)
    valid = np.where(~np.isnan(p))[0]
    order = valid[np.argsort(p[valid])]
    m = len(order)
    running = 0.0
    for rank, idx in enumerate(order):
        running = max(running, min(1.0, (m - rank) * p[idx]))
        out[idx] = running
    return [float(x) for x in out]


def cliffs_delta(x: Sequence[float], y: Sequence[float]) -> float:
    """Cliff's delta: P(x > y) - P(x < y) over all pairs, in [-1, 1]."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if x.size == 0 or y.size == 0:
        return NAN
    greater = (x[:, None] > y[None, :]).sum()
    less = (x[:, None] < y[None, :]).sum()
    return float(greater - less) / (x.size * y.size)


# ---- bootstrap ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Bootstrap:
    estimate: float
    low: float
    high: float
    n_valid: int  # resamples in which the statistic was defined
    resamples: int
    p_value: float = NAN  # two-sided percentile p-value against `null` (see bootstrap_ci)


def bootstrap_draws(
    statistic: Callable[[np.ndarray], float], n_units: int, *, resamples: int, seed: int
) -> list[float]:
    """The finite values of `statistic` over `resamples` bootstrap resamples of the units."""
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(resamples):
        value = statistic(rng.integers(0, n_units, size=n_units))
        if np.isfinite(value):
            draws.append(float(value))
    return draws


def bootstrap_p(draws: Sequence[float], null: float = 0.0) -> float:
    """Two-sided bootstrap p-value for H0: statistic = `null`: twice the smaller tail share of the
    resampled values beyond `null`, with the +1 correction so it is never exactly zero."""
    if len(draws) == 0:
        return NAN
    arr = np.asarray(draws, dtype=float)
    below = (np.sum(arr <= null) + 1) / (arr.size + 1)
    above = (np.sum(arr >= null) + 1) / (arr.size + 1)
    return float(min(1.0, 2.0 * min(below, above)))


def bootstrap_ci(
    statistic: Callable[[np.ndarray], float],
    n_units: int,
    *,
    resamples: int = 2000,
    seed: int = 42,
    confidence: float = 0.95,
    null: float | None = None,
) -> Bootstrap:
    """Percentile bootstrap over units (here: companies). `statistic` receives an array of unit
    indices (with repeats) and returns a number or NaN. With `null` the result also carries the
    two-sided bootstrap p-value against that value (used for differences, null = 0)."""
    estimate = float(statistic(np.arange(n_units)))
    draws = bootstrap_draws(statistic, n_units, resamples=resamples, seed=seed)
    if len(draws) < max(10, resamples // 20):
        return Bootstrap(estimate, NAN, NAN, len(draws), resamples)
    a = (1 - confidence) / 2 * 100
    low, high = np.percentile(draws, [a, 100 - a])
    p = bootstrap_p(draws, null) if null is not None else NAN
    return Bootstrap(estimate, float(low), float(high), len(draws), resamples, p)
