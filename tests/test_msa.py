"""Attribute agreement analysis, checked against percentages worked out by hand."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from gauge.msa.attribute import attribute_agreement
from gauge.stats.primitives import clopper_pearson

L, A, G = "Leader", "Average", "Laggard"
STANDARD = {"c1": L, "c2": A, "c3": G, "c4": A}

# (model, repetition, company) -> class
RATINGS = {
    ("M1", 1, "c1"): L, ("M1", 2, "c1"): L,
    ("M1", 1, "c2"): A, ("M1", 2, "c2"): A,
    ("M1", 1, "c3"): G, ("M1", 2, "c3"): A,
    ("M1", 1, "c4"): L, ("M1", 2, "c4"): L,
    ("M2", 1, "c1"): L, ("M2", 2, "c1"): L,
    ("M2", 1, "c2"): A, ("M2", 2, "c2"): L,
    ("M2", 1, "c3"): G, ("M2", 2, "c3"): G,
    ("M2", 1, "c4"): A, ("M2", 2, "c4"): A,
}  # fmt: skip


COLUMNS = ["model_key", "condition", "repetition", "company_code", "t2_class"]


def frame(ratings=RATINGS, condition="C1"):
    return pd.DataFrame(
        [(m, condition, r, c, cls) for (m, r, c), cls in ratings.items()], columns=COLUMNS
    )


def test_the_four_percentages_by_hand():
    res = attribute_agreement(frame(), STANDARD, "C1", ["M1", "M2"], [1, 2])
    # M1 trials agree for c1, c2, c4 (not c3); all equal the standard for c1, c2 only (c3: A on rep 2;
    # c4: Leader against Average)
    assert (res.within["M1"].k, res.within["M1"].n) == (3, 4)
    assert (res.vs_standard["M1"].k, res.vs_standard["M1"].n) == (2, 4)
    # M2 trials agree for c1, c3, c4 (not c2); all equal the standard for c1, c3, c4
    assert (res.within["M2"].k, res.within["M2"].n) == (3, 4)
    assert (res.vs_standard["M2"].k, res.vs_standard["M2"].n) == (3, 4)
    # every trial of both models identical: only c1 (all Leader); and equal to the standard: only c1
    assert (res.between.k, res.between.n) == (1, 4)
    assert (res.all_vs_standard.k, res.all_vs_standard.n) == (1, 4)
    assert res.within["M1"].rate == 0.75 and res.between.rate == 0.25


def test_intervals_are_exact_binomial():
    res = attribute_agreement(frame(), STANDARD, "C1", ["M1", "M2"], [1, 2])
    low, high = clopper_pearson(3, 4)
    assert (res.within["M1"].low, res.within["M1"].high) == (low, high)
    low, high = clopper_pearson(1, 4)
    assert (res.between.low, res.between.high) == (low, high)


def test_kappa_against_the_standard_by_hand():
    # M1's 8 (model, standard) pairs: LL x2, AA x2, GG, AG, LA x2 -> po = 5/8;
    # model margins L4 A3 G1, standard margins L2 A4 G2 -> pe = (8 + 12 + 2) / 64
    # kappa = (.625 - .34375) / (1 - .34375) = 3/7
    res = attribute_agreement(frame(), STANDARD, "C1", ["M1", "M2"], [1, 2])
    assert res.kappa_vs_standard["M1"] == pytest.approx(3 / 7)


def test_a_missing_rating_drops_that_company_from_the_cells_that_need_it():
    ratings = {k: v for k, v in RATINGS.items() if k != ("M2", 2, "c3")}
    res = attribute_agreement(frame(ratings), STANDARD, "C1", ["M1", "M2"], [1, 2])
    assert res.within["M1"].n == 4 and res.within["M2"].n == 3  # c3 lacks M2's second trial
    assert (res.within["M2"].k, res.vs_standard["M2"].k) == (2, 2)  # c1 and c4 (c2 disagrees)
    assert res.between.n == 3  # the cells that need both models drop c3 too
    assert (res.between.k, res.all_vs_standard.k) == (1, 1)


def test_conditions_are_kept_apart():
    both = pd.concat([frame(RATINGS, "C1"), frame({k: A for k in RATINGS}, "C2")])
    c1 = attribute_agreement(both, STANDARD, "C1", ["M1", "M2"], [1, 2])
    c2 = attribute_agreement(both, STANDARD, "C2", ["M1", "M2"], [1, 2])
    assert c1.between.k == 1
    assert (
        c2.between.k == 4 and c2.all_vs_standard.k == 2
    )  # all Average: equals the standard for c2, c4


def test_no_data_gives_empty_cells_not_errors():
    res = attribute_agreement(frame({}), STANDARD, "C1", ["M1", "M2"], [1, 2])
    assert res.within["M1"].n == 0 and math.isnan(res.within["M1"].rate)
    assert math.isnan(res.within["M1"].low) and res.between.n == 0
    assert math.isnan(res.kappa_vs_standard["M1"])


def test_a_single_trial_is_always_consistent_with_itself():
    one = {k: v for k, v in RATINGS.items() if k[1] == 1}
    res = attribute_agreement(frame(one), STANDARD, "C1", ["M1", "M2"], [1])
    assert res.within["M1"].k == res.within["M1"].n == 4  # nothing to disagree with
    assert (res.vs_standard["M1"].k, res.vs_standard["M2"].k) == (
        3,
        4,
    )  # M1 misses c4; M2 matches every company
