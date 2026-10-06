"""Statistical primitives, checked against values worked out by hand (see the comments) or against
published reference values (Krippendorff 2011; Fleiss 1971 as reproduced in standard texts)."""

from __future__ import annotations

import math

import numpy as np
import pytest
from statsmodels.stats.inter_rater import fleiss_kappa as sm_fleiss

from gauge.stats.primitives import (
    binomial_greater,
    bootstrap_ci,
    cliffs_delta,
    clopper_pearson,
    cohen_kappa,
    exact_mcnemar,
    fleiss_kappa,
    holm,
    krippendorff_alpha,
    paired_odds_ratio,
)

NAN = float("nan")


# ---- Cohen's kappa -------------------------------------------------------------------------------
def pairs(spec: dict[tuple, int]):
    a = [x for (x, _y), n in spec.items() for _ in range(n)]
    b = [y for (_x, y), n in spec.items() for _ in range(n)]
    return a, b


def test_cohen_kappa_textbook_2x2():
    # 20 AA, 5 AB, 10 BA, 15 BB: po = 35/50 = .7; rater 1 splits 25/25, rater 2 30/20, so
    # pe = (25*30 + 25*20) / 50^2 = .5 and kappa = (.7 - .5) / (1 - .5) = .4
    a, b = pairs({("A", "A"): 20, ("A", "B"): 5, ("B", "A"): 10, ("B", "B"): 15})
    assert cohen_kappa(a, b) == pytest.approx(0.4)


ORDINAL = {(1, 1): 2, (1, 2): 1, (2, 2): 2, (2, 3): 1, (3, 3): 2, (3, 2): 1}


def test_weighted_kappas_by_hand():
    a, b = pairs(ORDINAL)  # n = 9; column margins 2, 4, 3; row margins 3, 3, 3
    assert cohen_kappa(a, b) == pytest.approx(0.5)  # po 6/9, pe 1/3
    # quadratic: observed disagreement 3 * .25 / 9 = .08333; expected 8.25 / 27 = .30556
    assert cohen_kappa(a, b, weights="quadratic") == pytest.approx(8 / 11)
    # linear: observed 1.5 / 9; expected 11.5 / 27
    assert cohen_kappa(a, b, weights="linear") == pytest.approx(14 / 23)


def test_kappa_edge_cases():
    assert cohen_kappa([1, 2, 3, 2], [1, 2, 3, 2]) == pytest.approx(1.0)
    assert math.isnan(cohen_kappa([3, 3, 3], [3, 3, 3]))  # one category: chance agreement is 1
    assert math.isnan(cohen_kappa([], []))
    assert cohen_kappa(["a", "b", "a", "b"], ["b", "a", "b", "a"]) == pytest.approx(-1.0)
    with pytest.raises(ValueError):
        cohen_kappa([1], [1, 2])
    with pytest.raises(ValueError):
        cohen_kappa([1], [1], weights="cubic")


def test_padding_the_label_set_with_unused_categories_changes_nothing():
    """Equally spaced weights scale both disagreement sums alike, and unused categories carry no
    mass, so fixing the T3 scale at 1..5 gives the same kappa as the categories actually used."""
    a, b = pairs(ORDINAL)
    for weights in (None, "linear", "quadratic"):
        padded = cohen_kappa(a, b, weights=weights, labels=[1, 2, 3, 4, 5])
        assert padded == pytest.approx(cohen_kappa(a, b, weights=weights))
    with pytest.raises(KeyError):
        cohen_kappa([1, 9], [1, 1], labels=[1, 2, 3])  # a value outside the declared scale


# ---- Fleiss' kappa -------------------------------------------------------------------------------
def test_fleiss_kappa_by_hand():
    # 2 raters, 3 items: P_i = 1, 1, 0 so P = 2/3; categories split 3/3 so Pe = .5; kappa = 1/3
    assert fleiss_kappa(np.array([[2, 0], [0, 2], [1, 1]])) == pytest.approx(1 / 3)


FLEISS_EXAMPLE = np.array(
    [
        [0, 0, 0, 0, 14],
        [0, 2, 6, 4, 2],
        [0, 0, 3, 5, 6],
        [0, 3, 9, 2, 0],
        [2, 2, 8, 1, 1],
        [7, 7, 0, 0, 0],
        [3, 2, 6, 3, 0],
        [2, 5, 3, 2, 2],
        [6, 5, 2, 1, 0],
        [0, 2, 2, 3, 7],
    ]
)  # 10 items, 14 raters, 5 categories: the standard worked example, kappa = .210


def test_fleiss_kappa_matches_the_worked_example_and_statsmodels():
    value = fleiss_kappa(FLEISS_EXAMPLE)
    assert value == pytest.approx(0.2099, abs=5e-4)
    assert value == pytest.approx(sm_fleiss(FLEISS_EXAMPLE, method="fleiss"))


def test_fleiss_kappa_rejects_uneven_raters_and_is_nan_without_variation():
    with pytest.raises(ValueError):
        fleiss_kappa(np.array([[2, 0], [1, 0]]))
    assert math.isnan(fleiss_kappa(np.array([[3, 0], [3, 0]])))


# ---- Krippendorff's alpha ------------------------------------------------------------------------
KRIPPENDORFF_2011 = np.array(
    [
        [1, 2, 3, 3, 2, 1, 4, 1, 2, NAN, NAN, NAN],
        [1, 2, 3, 3, 2, 2, 4, 1, 2, 5, NAN, 3],
        [NAN, 3, 3, 3, 2, 3, 4, 2, 2, 5, 1, NAN],
        [1, 2, 3, 3, 2, 4, 4, 1, 2, 5, 1, NAN],
    ]
)


def test_alpha_reproduces_krippendorffs_published_example():
    assert krippendorff_alpha(KRIPPENDORFF_2011, "nominal") == pytest.approx(0.743, abs=5e-4)
    assert krippendorff_alpha(KRIPPENDORFF_2011, "ordinal") == pytest.approx(0.815, abs=5e-4)


def test_nominal_alpha_by_hand():
    # raters A=[1,1,2,2], B=[1,2,2,2]: coincidences o11=2, o12=o21=1, o22=4 (n=8), marginals 3 and 5
    # Do = 2/8 = .25, De = 2*3*5 / (8*7) = .5357, alpha = 1 - .25/.5357 = 8/15
    assert krippendorff_alpha(np.array([[1, 1, 2, 2], [1, 2, 2, 2]]), "nominal") == pytest.approx(
        8 / 15
    )


def test_alpha_is_nan_when_undefined_and_perfect_when_raters_agree():
    assert math.isnan(krippendorff_alpha(np.ones((3, 5)), "nominal"))  # no variation at all
    assert math.isnan(krippendorff_alpha(np.ones((3, 5)), "ordinal"))
    same = np.array([[1, 2, 3, 4], [1, 2, 3, 4]])
    assert krippendorff_alpha(same, "nominal") == pytest.approx(1.0)
    assert krippendorff_alpha(same, "ordinal") == pytest.approx(1.0)


# ---- proportions and tests -----------------------------------------------------------------------
def test_clopper_pearson_closed_forms_and_a_symmetric_case():
    lo, hi = clopper_pearson(0, 10)
    assert lo == 0.0 and hi == pytest.approx(1 - 0.025 ** (1 / 10))  # .3085
    lo, hi = clopper_pearson(10, 10)
    assert hi == 1.0 and lo == pytest.approx(0.025 ** (1 / 10))  # .6915
    lo, hi = clopper_pearson(5, 10)
    assert (lo, hi) == (pytest.approx(0.1871, abs=5e-4), pytest.approx(0.8129, abs=5e-4))
    assert lo + hi == pytest.approx(1.0)
    assert all(math.isnan(x) for x in clopper_pearson(0, 0))


def test_clopper_pearson_covers_the_estimate_and_narrows_with_n():
    lo1, hi1 = clopper_pearson(8, 40)
    lo2, hi2 = clopper_pearson(80, 400)
    assert lo1 < 0.2 < hi1 and (hi2 - lo2) < (hi1 - lo1)


def test_exact_mcnemar_by_hand():
    assert exact_mcnemar(2, 8) == pytest.approx(2 * (1 + 10 + 45) / 1024)  # .109375
    assert exact_mcnemar(8, 2) == exact_mcnemar(2, 8)
    assert exact_mcnemar(5, 5) == 1.0 and exact_mcnemar(0, 0) == 1.0
    assert exact_mcnemar(0, 5) == pytest.approx(2 * 0.5**5)


def test_paired_odds_ratio():
    estimate, low, high = paired_odds_ratio(8, 2)
    assert estimate == 4.0 and low < 4.0 < high
    lo_p, hi_p = clopper_pearson(8, 10)
    assert low == pytest.approx(lo_p / (1 - lo_p)) and high == pytest.approx(hi_p / (1 - hi_p))
    assert paired_odds_ratio(3, 0)[0] == math.inf
    assert math.isnan(paired_odds_ratio(0, 0)[0])


def test_binomial_greater_by_hand():
    assert binomial_greater(8, 10) == pytest.approx((45 + 10 + 1) / 1024)
    assert binomial_greater(5, 10) > 0.5 and math.isnan(binomial_greater(0, 0))


def test_holm_by_hand():
    # sorted .005 x4 = .02, .01 x3 = .03, .03 x2 = .06, .04 x1 = .04 -> kept monotone at .06
    assert holm([0.01, 0.04, 0.03, 0.005]) == pytest.approx([0.03, 0.06, 0.06, 0.02])
    assert holm([0.5, 0.9]) == pytest.approx([1.0, 1.0])  # 2*.5 = 1, and never decreasing
    adjusted = holm([0.01, NAN, 0.04])  # NaN is outside the family: m = 2
    assert adjusted[0] == pytest.approx(0.02) and math.isnan(adjusted[1])
    assert adjusted[2] == pytest.approx(0.04)
    assert holm([]) == []


def test_cliffs_delta_by_hand():
    assert cliffs_delta([1, 2, 3], [2, 3, 4]) == pytest.approx(-5 / 9)  # 1 greater, 6 smaller of 9
    assert cliffs_delta([5, 6], [1, 2]) == 1.0 and cliffs_delta([1, 2], [1, 2]) == 0.0
    assert math.isnan(cliffs_delta([], [1]))


# ---- bootstrap -----------------------------------------------------------------------------------
def test_bootstrap_is_reproducible_and_brackets_the_estimate():
    data = np.array([3, 5, 4, 6, 5, 7, 4, 5, 6, 3, 5, 4, 6, 5, 7, 4, 5, 6, 3, 5], dtype=float)

    def mean(idx):
        return float(data[idx].mean())

    first = bootstrap_ci(mean, len(data), resamples=500, seed=7)
    again = bootstrap_ci(mean, len(data), resamples=500, seed=7)
    other = bootstrap_ci(mean, len(data), resamples=500, seed=8)
    assert first == again and first != other
    assert first.estimate == pytest.approx(data.mean())
    assert first.low < first.estimate < first.high and first.n_valid == 500
    # normal-theory half-width is about 1.96 * sd / sqrt(n) = 0.5: the bootstrap is close to it
    assert (first.high - first.low) / 2 == pytest.approx(
        1.96 * data.std(ddof=1) / math.sqrt(20), rel=0.25
    )


def test_bootstrap_with_a_constant_statistic_is_degenerate_not_an_error():
    result = bootstrap_ci(lambda idx: 0.5, 10, resamples=100)
    assert result.low == result.high == result.estimate == 0.5


def test_bootstrap_reports_nan_ci_when_the_statistic_is_mostly_undefined():
    state = {"n": 0}

    def sometimes(idx):
        state["n"] += 1
        return 1.0 if state["n"] % 50 == 0 else NAN  # defined in about 2% of the resamples

    result = bootstrap_ci(sometimes, 10, resamples=400)
    assert math.isnan(result.low) and math.isnan(result.high) and result.n_valid < 20


def test_bootstrap_resamples_units_with_repeats():
    seen = []

    def record(idx):
        seen.append(tuple(idx))
        return 0.0

    bootstrap_ci(record, 6, resamples=5, seed=1)
    assert seen[0] == tuple(range(6))  # the first call is the full sample, in order
    assert all(len(s) == 6 and all(0 <= i < 6 for i in s) for s in seen)
    assert any(len(set(s)) < 6 for s in seen[1:])  # with replacement
