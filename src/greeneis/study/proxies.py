"""The two proxies a unit without a record would use, both leave-one-out.

- **Estimated**: spend divided by a typical price. The price is the median of value/quantity over the
  *other* units in the same price group and item.
- **Default**: a sector-typical intensity times the unit's own scale. The intensity is the median of
  quantity/scale over the *other* units in the same sector and item.

Leave-one-out keeps a unit's own record out of its own proxy, so the error is a real prediction error.
A proxy is NaN when fewer than `min_others` other units are available.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MIN_OTHERS = 4  # placeholder: fewer other units than this and the proxy is not formed


def loo_median(x: np.ndarray) -> np.ndarray:
    """For each element, the median of all the other elements. NaN when there is only one element."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    out = np.full(n, np.nan)
    if n < 2:
        return out
    order = np.argsort(x, kind="stable")
    s = x[order]
    rank = np.empty(n, dtype=int)
    rank[order] = np.arange(n)  # position of each element in sorted order
    m = n - 1  # size of the remaining set

    def kth(
        j: int,
    ) -> np.ndarray:  # j-th (0-based) of the sorted remaining set, per removed element
        return np.where(j < rank, s[j], s[j + 1])

    out = kth((m - 1) // 2) if m % 2 == 1 else (kth(m // 2 - 1) + kth(m // 2)) / 2
    return out


def _loo_by_group(
    df: pd.DataFrame, values: pd.Series, keys: list[str], min_others: int
) -> pd.Series:
    def one(s: pd.Series) -> pd.Series:
        if len(s) - 1 < min_others:
            return pd.Series(np.nan, index=s.index)
        return pd.Series(loo_median(s.to_numpy()), index=s.index)

    return values.groupby([df[k] for k in keys], group_keys=False).apply(one)


def add_proxies(cases: pd.DataFrame, min_others: int = MIN_OTHERS) -> pd.DataFrame:
    """Add typical_price, intensity, q_estimated, q_default and their relative errors."""
    df = cases.copy()
    price = df["value_inr"] / df["quantity"]
    intensity = df["quantity"] / df["scale"]
    df["typical_price"] = _loo_by_group(df, price, ["price_group", "item_id"], min_others)
    df["typical_intensity"] = _loo_by_group(df, intensity, ["sector", "item_id"], min_others)
    df["q_estimated"] = df["value_inr"] / df["typical_price"]
    df["q_default"] = df["typical_intensity"] * df["scale"]
    df["eps_estimated"] = (df["q_estimated"] - df["quantity"]) / df["quantity"]
    df["eps_default"] = (df["q_default"] - df["quantity"]) / df["quantity"]
    return df
