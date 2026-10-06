"""Rounding, T2 and T3-update rules. Expected values are worked out by hand."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from gauge.rules.rounding import grouped, plain, sig_round
from gauge.rules.t2 import CutPoints, T2Rule, apply_t2, classify, score_metric
from gauge.rules.t3 import (
    T3Rule,
    benchmark_signal,
    expected_direction,
    label_transition,
    signals,
    trend_signal,
)

D = Decimal
SCORES = {"best": 2, "middle": 1, "worst": 0}
CLASSES = {"Leader": (5, 6), "Average": (2, 4), "Laggard": (0, 1)}
CUTS = CutPoints(p33=D("10"), p67=D("20"), n=5)


# ---- rounding ----------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value, figures, expected",
    [
        ("1092.65", 4, "1093"),
        ("0.14724", 4, "0.1472"),
        ("58.425", 4, "58.42"),  # half-even: the 2 is even
        ("58.435", 4, "58.44"),  # half-even: round up to the even 4
        ("100", 4, "100.0"),
        ("-1234.5", 4, "-1234"),
        ("0.0001234567", 4, "0.0001235"),
        ("623812739", 4, "623800000"),
        ("0", 4, "0"),
    ],
)
def test_sig_round_half_even(value, figures, expected):
    assert plain(sig_round(D(value), figures)) == expected


def test_grouping_and_plain_text():
    assert grouped(D("623812700")) == "623,812,700"
    assert grouped(D("88511.5")) == "88,511.5"
    assert grouped(D("0.0001234")) == "0.0001234"
    assert grouped(D("-1234567")) == "-1,234,567"
    assert plain(D("1.093E+3")) == "1093"  # never an exponent


# ---- T2 ----------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value, better, expected",
    [
        ("10", "lower", 2),
        ("9.99", "lower", 2),  # at the cut: the better tertile
        ("10.01", "lower", 1),
        ("20", "lower", 1),  # at the upper cut: still middle
        ("20.01", "lower", 0),
        ("20", "higher", 2),
        ("25", "higher", 2),  # at the cut: the better tertile
        ("19.99", "higher", 1),
        ("10", "higher", 1),
        ("9.99", "higher", 0),
    ],
)
def test_score_metric_boundaries(value, better, expected):
    assert score_metric(D(value), CUTS, better, SCORES) == expected


@pytest.mark.parametrize(
    "total, expected",
    [
        (6, "Leader"),
        (5, "Leader"),
        (4, "Average"),
        (3, "Average"),
        (2, "Average"),
        (1, "Laggard"),
        (0, "Laggard"),
    ],
)
def test_classify_totals(total, expected):
    assert classify(total, CLASSES) == expected


def make_rule(**changes) -> T2Rule:
    data = {
        "rule_id": "t2_v1",
        "analysis_fy": "FY2024-25",
        "display_significant_figures": 4,
        "metrics": [
            {"kpi": "emissions_intensity", "better": "lower"},
            {"kpi": "water_intensity", "better": "lower"},
            {"kpi": "renewable_share", "better": "higher"},
        ],
        "scores": SCORES,
        "classes": CLASSES,
        "tie_rule": "better tertile",
        "cut_points": {
            "Cement": {
                "emissions_intensity": {"p33": "700", "p67": "1000", "n": 5},
                "water_intensity": {"p33": "250", "p67": "400", "n": 5},
                "renewable_share": {"p33": "5", "p67": "8", "n": 5},
            }
        },
    }
    return T2Rule(**{**data, **changes})


def test_apply_t2_hand_worked_companies():
    rule = make_rule()
    # lowest emissions and water, highest renewables: 2 + 2 + 2 = 6 -> Leader
    best = apply_t2(
        rule,
        "Cement",
        {"emissions_intensity": D("650"), "water_intensity": D("200"), "renewable_share": D("9")},
    )
    assert (best.scores, best.total, best.t2_class) == (
        {"emissions_intensity": 2, "water_intensity": 2, "renewable_share": 2},
        6,
        "Leader",
    )
    # middle on all three: 1 + 1 + 1 = 3 -> Average
    mid = apply_t2(
        rule,
        "Cement",
        {"emissions_intensity": D("800"), "water_intensity": D("300"), "renewable_share": D("6")},
    )
    assert (mid.total, mid.t2_class) == (3, "Average")
    # worst on two, middle on one: 0 + 0 + 1 = 1 -> Laggard
    low = apply_t2(
        rule,
        "Cement",
        {"emissions_intensity": D("1200"), "water_intensity": D("500"), "renewable_share": D("6")},
    )
    assert (low.total, low.t2_class) == (1, "Laggard")
    # one best, two worst: 2 + 0 + 0 = 2 -> Average (the boundary between Average and Laggard)
    edge = apply_t2(
        rule,
        "Cement",
        {"emissions_intensity": D("700"), "water_intensity": D("500"), "renewable_share": D("4")},
    )
    assert (edge.total, edge.t2_class) == (2, "Average")


def test_unknown_sector_is_an_error():
    with pytest.raises(KeyError):
        apply_t2(make_rule(), "Steel", {})


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"scores": {"best": 1, "middle": 1, "worst": 0}}, "best > middle > worst"),
        (
            {"classes": {"Leader": (5, 6), "Average": (2, 3), "Laggard": (0, 1)}},
            "cover every total score",
        ),
        ({"classes": {"Leader": (5, 6), "Average": (2, 4)}}, "classes must be exactly"),
        (
            {"cut_points": {"Cement": {"emissions_intensity": {"p33": "1", "p67": "2", "n": 5}}}},
            "must cover exactly",
        ),
    ],
)
def test_rule_validation(changes, message):
    with pytest.raises(ValidationError, match=message):
        make_rule(**changes)


def test_cut_points_must_be_ordered_and_have_enough_companies():
    with pytest.raises(ValidationError, match="must not exceed"):
        CutPoints(p33=D("5"), p67=D("4"), n=5)
    with pytest.raises(ValidationError):
        CutPoints(p33=D("1"), p67=D("2"), n=2)


# ---- T3 update rule ----------------------------------------------------------------------------
def make_t3() -> T3Rule:
    return T3Rule(
        rule_id="t3_update_v1",
        core_metrics=[
            {"kpi": "e", "better": "lower"},
            {"kpi": "w", "better": "lower"},
            {"kpi": "r", "better": "higher"},
        ],
        trend={
            "from_fy": "FY2022-23",
            "to_fy": "FY2024-25",
            "threshold_pct": "5",
            "min_metrics": 2,
        },
        benchmark={"fy": "FY2024-25", "against": "sector_median", "min_metrics": 2},
    )


def kv(e, w, r):
    return {"e": D(e), "w": D(w), "r": D(r)}


def test_trend_signal_counts_improvements_by_direction():
    t3 = make_t3()
    old = kv("100", "50", "10")
    # emissions 100 -> 90 (-10%: improved), water 50 -> 51 (+2%: neither),
    # renewables 10 -> 11 (+10%: improved)
    assert trend_signal(t3, old, kv("90", "51", "11")) == 1
    # emissions +10% (worse), water +20% (worse), renewables -10% (worse)
    assert trend_signal(t3, old, kv("110", "60", "9")) == -1
    # one improved, one worsened, one flat: neither reaches 2
    assert trend_signal(t3, old, kv("90", "60", "10")) == 0


def test_trend_threshold_is_inclusive_at_exactly_five_percent():
    t3 = make_t3()
    old = kv("100", "100", "100")
    assert (
        trend_signal(t3, old, kv("95", "95", "100")) == 1
    )  # exactly -5% on two lower-is-better metrics
    assert trend_signal(t3, old, kv("95.01", "95.01", "100")) == 0  # -4.99%: not enough
    assert (
        trend_signal(t3, old, kv("100", "100", "95")) == 0
    )  # renewables -5% is one worsening only


def test_change_from_zero_is_judged_by_sign():
    t3 = make_t3()
    zero = kv("0", "0", "0")
    assert trend_signal(t3, zero, kv("0", "0", "0")) == 0
    assert (
        trend_signal(t3, zero, kv("1", "1", "0")) == -1
    )  # two lower-is-better KPIs rose from zero
    assert trend_signal(t3, zero, kv("0", "0", "5")) == 0  # only renewables improved


def test_benchmark_signal_uses_the_median_and_ignores_ties():
    t3 = make_t3()
    med = kv("100", "50", "10")
    assert (
        benchmark_signal(t3, kv("90", "40", "5"), med) == 1
    )  # better on emissions and water, worse on renewables
    assert benchmark_signal(t3, kv("110", "60", "5"), med) == -1  # worse on all three
    assert benchmark_signal(t3, kv("100", "50", "10"), med) == 0  # all equal: neither
    assert benchmark_signal(t3, kv("90", "60", "10"), med) == 0  # one better, one worse, one equal
    assert (
        benchmark_signal(t3, kv("90", "50", "12"), med) == 1
    )  # better on emissions and renewables, equal on water


@pytest.mark.parametrize(
    "trend, bench, expected",
    [
        (1, 1, "up"),
        (1, 0, "up"),
        (0, 1, "up"),
        (-1, -1, "down"),
        (-1, 0, "down"),
        (0, -1, "down"),
        (1, -1, "none"),
        (-1, 1, "none"),
        (0, 0, "none"),
    ],
)
def test_expected_direction(trend, bench, expected):
    assert expected_direction(trend, bench) == expected


@pytest.mark.parametrize(
    "expected, c1, c2, label, delta",
    [
        ("up", 3, 4, "consistent", 1),
        ("up", 3, 3, "consistent", 0),
        ("up", 3, 2, "violating", -1),
        ("down", 3, 2, "consistent", -1),
        ("down", 3, 3, "consistent", 0),
        ("down", 3, 5, "violating", 2),
        ("none", 3, 5, "unconstrained", 2),
        ("none", 4, 1, "unconstrained", -3),
    ],
)
def test_label_transition(expected, c1, c2, label, delta):
    assert label_transition(expected, c1, c2) == (label, delta)


def test_signals_combines_the_two_signals():
    t3 = make_t3()
    s = signals(t3, kv("100", "50", "10"), kv("90", "45", "12"), kv("100", "50", "10"))
    assert (s.trend, s.benchmark, s.expected) == (1, 1, "up")
    mixed = signals(t3, kv("100", "50", "10"), kv("90", "45", "12"), kv("80", "40", "20"))
    assert (mixed.trend, mixed.benchmark, mixed.expected) == (1, -1, "none")
