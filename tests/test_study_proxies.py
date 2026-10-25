"""Leave-one-out proxies against hand calculations and a brute-force reference."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from greeneis.study.cases import CaseError, validate
from greeneis.study.proxies import add_proxies, loo_median


def test_loo_median_by_hand():
    # [1, 2, 3, 10]: drop 1 -> median(2,3,10)=3; drop 2 -> median(1,3,10)=3;
    # drop 3 -> median(1,2,10)=2; drop 10 -> median(1,2,3)=2
    assert loo_median(np.array([1, 2, 3, 10])).tolist() == [3, 3, 2, 2]
    # [1, 5, 9]: drop 1 -> median(5,9)=7; drop 5 -> median(1,9)=5; drop 9 -> median(1,5)=3
    assert loo_median(np.array([1, 5, 9])).tolist() == [7, 5, 3]
    # input order does not matter
    assert loo_median(np.array([9, 1, 5])).tolist() == [3, 7, 5]


def test_loo_median_edge_cases():
    assert np.isnan(loo_median(np.array([4.0]))).all()
    assert loo_median(np.array([2.0, 8.0])).tolist() == [8, 2]  # the median of one value is itself
    assert loo_median(np.array([3.0, 3.0, 3.0])).tolist() == [3, 3, 3]


@pytest.mark.parametrize("seed", range(5))
def test_loo_median_matches_brute_force(seed):
    rng = np.random.default_rng(seed)
    x = rng.integers(0, 20, size=int(rng.integers(2, 40))).astype(float)  # ties included
    brute = [np.median(np.delete(x, i)) for i in range(len(x))]
    assert loo_median(x).tolist() == pytest.approx(brute)


def cases_frame():
    # six units, one item, one price group, one sector. Prices (value / quantity): 10, 10, 10, 10, 20, 5
    rows = []
    for i, (q, v, scale) in enumerate(
        [
            (100, 1000, 10),
            (200, 2000, 10),
            (300, 3000, 20),
            (400, 4000, 20),
            (500, 10000, 25),
            (600, 3000, 30),
        ]
    ):
        rows.append((f"u{i}", "coal", q, v, scale, "S", "G", "G", False))
    return pd.DataFrame(
        rows,
        columns=[
            "unit_id",
            "item_id",
            "quantity",
            "value_inr",
            "scale",
            "sector",
            "price_group",
            "cluster",
            "synthetic",
        ],
    )


def test_estimated_proxy_by_hand():
    out = add_proxies(cases_frame(), min_others=4)
    # unit u0: other prices 10, 10, 10, 20, 5 -> median 10; q_hat = 1000 / 10 = 100; error 0
    assert out.loc[0, "typical_price"] == 10 and out.loc[0, "q_estimated"] == 100
    assert out.loc[0, "eps_estimated"] == 0
    # unit u4 (price 20): others 10, 10, 10, 10, 5 -> median 10; q_hat = 10000 / 10 = 1000 vs 500 -> +100%
    assert out.loc[4, "typical_price"] == 10 and out.loc[4, "q_estimated"] == 1000
    assert out.loc[4, "eps_estimated"] == 1.0
    # unit u5 (price 5): others 10, 10, 10, 10, 20 -> median 10; q_hat = 3000 / 10 = 300 vs 600 -> -50%
    assert out.loc[5, "eps_estimated"] == -0.5


def test_default_proxy_by_hand():
    out = add_proxies(cases_frame(), min_others=4)
    # intensities q / scale: 10, 20, 15, 20, 20, 20. For u0: others 20, 15, 20, 20, 20 -> median 20;
    # q_default = 20 x 10 = 200 vs 100 -> +100%
    assert out.loc[0, "typical_intensity"] == 20 and out.loc[0, "q_default"] == 200
    assert out.loc[0, "eps_default"] == 1.0
    # u2 (intensity 15): others 10, 20, 20, 20, 20 -> 20; q_default = 20 x 20 = 400 vs 300 -> +33.3%
    assert out.loc[2, "eps_default"] == pytest.approx(1 / 3)


def test_a_unit_is_never_used_to_predict_itself():
    df = cases_frame()
    df.loc[4, ["quantity", "value_inr"]] = [500, 10**9]  # an absurd price for u4 alone
    out = add_proxies(df, min_others=4)
    # the other units' proxies see u4's absurd price, but u4's own typical price must not
    assert out.loc[4, "typical_price"] == 10


def test_proxy_is_nan_below_the_minimum_group_size():
    out = add_proxies(cases_frame().head(4), min_others=4)  # 3 others only
    assert out["q_estimated"].isna().all() and out["q_default"].isna().all()


def test_validate_counts_every_drop():
    df = cases_frame()
    df.loc[0, "quantity"] = -1
    df.loc[1, "item_id"] = "peat"
    df.loc[2, "value_inr"] = np.nan
    result = validate(df)
    assert len(result.cases) == 3
    assert result.dropped == {
        "unknown item_id": 1,
        "quantity missing or not positive": 1,
        "value_inr missing or not positive": 1,
    }


def test_validate_refuses_missing_columns_and_empty_results():
    with pytest.raises(CaseError, match="missing columns"):
        validate(cases_frame().drop(columns=["scale"]))
    bad = cases_frame()
    bad["quantity"] = -1
    with pytest.raises(CaseError, match="no usable rows"):
        validate(bad)


def test_duplicate_unit_item_rows_are_dropped_together():
    df = pd.concat([cases_frame(), cases_frame().head(1)], ignore_index=True)
    result = validate(df)
    assert result.dropped == {"duplicate unit and item": 2}
    assert len(result.cases) == 5
