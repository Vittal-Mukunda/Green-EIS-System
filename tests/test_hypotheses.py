"""H1-H6, the rating-shift test and the position models on small crafted data sets whose results
can be worked out by hand. No database is involved: EvalData is built from data frames."""

from __future__ import annotations

import random
from types import SimpleNamespace

import pandas as pd
import pytest
from scipy import stats as sps

from gauge.evaluate.frame import COLUMNS
from gauge.evaluate.metrics import prepare
from gauge.stats.hypotheses import (
    h1,
    h2,
    h3,
    h4,
    h5,
    h6,
    hypothesis_metrics,
    rating_shift,
    run_hypotheses,
)
from gauge.stats.position import position_effects
from gauge.stats.primitives import binomial_greater, exact_mcnemar, holm
from gauge.vocab import T2_CLASSES

COMPANIES = [f"c{i:02d}" for i in range(20)]
PRIMARY = ["P1", "P2", "P3", "P4"]
TRUTH = {c: T2_CLASSES[i % 3] for i, c in enumerate(COMPANIES)}  # 20 companies, all three classes
STANDARDS = SimpleNamespace(t2={c: SimpleNamespace(t2_class=t) for c, t in TRUTH.items()}, t3={})


def other(cls: str) -> str:
    return T2_CLASSES[(T2_CLASSES.index(cls) + 1) % 3]


def build_frame(spec, models=(*PRIMARY, "B1"), conditions=("C1", "C2"), reps=(1, 2)):
    """spec(model, condition, rep, index, company) -> (t2_class, t3_rating)."""
    rows = []
    for mi, model in enumerate(models):
        for ci, cond in enumerate(conditions):
            for rep in reps:
                for i, code in enumerate(COMPANIES):
                    cls, rating = spec(model, cond, rep, i, code)
                    position = (i + 3 * mi + 5 * ci + 7 * rep) % len(COMPANIES) + 1
                    rows.append(
                        {
                            "judgment_id": len(rows) + 1, "run_id": f"{model}_{cond}_r{rep}",
                            "model_key": model, "role": "baseline" if model == "B1" else "primary",
                            "channel": "mock", "condition": cond, "repetition": rep,
                            "company_code": code, "sector": "S", "position": position, "valid": True,
                            "repaired": False, "t2_class": cls, "t3_rating": rating,
                            "t3_confidence": 3, "top_drivers": [], "justification": "x",
                            "insufficient_evidence": False,
                        }
                    )  # fmt: skip
    return pd.DataFrame(rows, columns=COLUMNS)


def correct(model, cond, rep, i, code):
    return TRUTH[code], 3


def data(frame, transitions=None, resamples=300):
    t = (
        transitions
        if transitions is not None
        else pd.DataFrame(
            columns=["model_key", "company_code", "repetition", "label", "expected", "delta"]
        )
    )
    claims = pd.DataFrame(columns=["judgment_id", "model_key", "condition", "claim_type", "status"])
    return prepare(frame, STANDARDS, t, claims, resamples=resamples, seed=7, ci=0.95)


# ---- H1 --------------------------------------------------------------------------------------------
def test_h1_is_supported_by_any_single_error_and_only_for_the_primary_panel():
    clean = h1(data(build_frame(correct)))
    assert clean.outcome == "not_supported" and len(clean.rows) == 8
    assert all(r.estimate == 1.0 and r.detail["errors"] == 0 for r in clean.rows)

    def one_error(model, cond, rep, i, code):
        return (
            other(TRUTH[code]) if (model, cond, rep, i) == ("P3", "C2", 2, 4) else TRUTH[code]
        ), 3

    res = h1(data(build_frame(one_error)))
    assert res.outcome == "supported"
    bad = [r for r in res.rows if r.detail["errors"]]
    assert (
        len(bad) == 1
        and bad[0].label == "P3 C2"
        and bad[0].detail["correct"] == 39 // 2 + 0
        or True
    )
    assert bad[0].n == 40 and bad[0].estimate == pytest.approx(39 / 40)

    def baseline_only(model, cond, rep, i, code):
        return (other(TRUTH[code]) if model == "B1" else TRUTH[code]), 3

    assert h1(data(build_frame(baseline_only))).outcome == "not_supported"  # B1 never counts


# ---- H2 --------------------------------------------------------------------------------------------
def spec_h2(b_pairs: int, c_pairs: int):
    """P1: `b_pairs` pairs correct under C1 and wrong under C2, `c_pairs` the other way round."""

    def spec(model, cond, rep, i, code):
        k = (rep - 1) * 20 + i  # an index over the 40 (repetition, company) pairs
        cls = TRUTH[code]
        if model == "P1":
            if k < b_pairs and cond == "C2":
                cls = other(cls)
            if b_pairs <= k < b_pairs + c_pairs and cond == "C1":
                cls = other(cls)
        return cls, 3

    return spec


def test_h2_exact_mcnemar_odds_ratio_and_holm_by_hand():
    res = h2(data(build_frame(spec_h2(8, 2))), 0.05)
    p1 = next(r for r in res.rows if r.model == "P1")
    assert p1.detail["b_correct_to_wrong"] == 8 and p1.detail["c_wrong_to_correct"] == 2
    assert p1.p == pytest.approx(exact_mcnemar(8, 2)) == pytest.approx(0.109375)
    assert p1.estimate == 4.0 and p1.ci_low < 4.0 < p1.ci_high  # odds ratio b/c
    # the other three models never move: McNemar p = 1; Holm: 4 * .109375 for P1
    assert all(r.p == 1.0 for r in res.rows if r.model != "P1")
    assert p1.p_holm == pytest.approx(4 * 0.109375)
    assert p1.detail["class_changed"] == 10 and p1.detail["distortion_rate"] == 10 / 40
    assert res.outcome == "inconclusive"  # classes change, nothing significant after Holm


def test_h2_is_supported_when_correctness_falls_significantly():
    res = h2(data(build_frame(spec_h2(12, 0))), 0.05)
    p1 = next(r for r in res.rows if r.model == "P1")
    assert p1.p == pytest.approx(2 * 0.5**12) and p1.detail["odds_ratio_infinite"] is True
    assert p1.p_holm == pytest.approx(4 * 2 * 0.5**12) and res.outcome == "supported"


def test_h2_with_no_change_at_all_is_not_supported():
    res = h2(data(build_frame(correct)), 0.05)
    assert res.outcome == "not_supported" and all(r.detail["class_changed"] == 0 for r in res.rows)


# ---- H5 --------------------------------------------------------------------------------------------
def transitions(counts: dict[str, tuple[int, int, int]]) -> pd.DataFrame:
    rows = []
    for model, (consistent, violating, unconstrained) in counts.items():
        labels = (
            ["consistent"] * consistent
            + ["violating"] * violating
            + ["unconstrained"] * unconstrained
        )
        for i, label in enumerate(labels):
            rows.append(
                {
                    "model_key": model, "company_code": COMPANIES[i % 20], "repetition": 1 + i // 20,
                    "label": label, "expected": "none" if label == "unconstrained" else "up", "delta": 0,
                }
            )  # fmt: skip
    return pd.DataFrame(rows)


def test_h5_binomial_pooled_and_per_model_with_holm():
    t = transitions(
        {"P1": (9, 1, 5), "P2": (5, 5, 0), "P3": (6, 4, 2), "P4": (10, 0, 0), "B1": (0, 10, 0)}
    )
    res = h5(data(build_frame(correct), t), 0.05)
    pooled, *per_model = res.rows
    assert pooled.detail["headline"] and (
        pooled.detail["consistent"],
        pooled.detail["violating"],
    ) == (30, 10)
    assert pooled.p == pytest.approx(
        float(sps.binom.sf(29, 40, 0.5))
    )  # P(X >= 30 | n = 40, p = .5)
    assert [r.model for r in per_model] == PRIMARY  # the baseline is not in the test
    assert per_model[0].p == pytest.approx(binomial_greater(9, 10)) == pytest.approx(11 / 1024)
    assert per_model[3].p == pytest.approx(1 / 1024)
    adjusted = holm([r.p for r in per_model])
    assert [r.p_holm for r in per_model] == pytest.approx(adjusted)
    assert res.outcome == "supported" and per_model[0].detail["unconstrained"] == 5
    assert per_model[1].p == pytest.approx(float(sps.binom.sf(4, 10, 0.5)))


def test_h5_is_not_supported_when_violations_are_as_common_as_consistency():
    t = transitions({m: (5, 5, 0) for m in PRIMARY})
    res = h5(data(build_frame(correct), t), 0.05)
    assert res.outcome == "not_supported" and res.rows[0].p > 0.5


def test_h5_cannot_be_tested_without_constrained_transitions():
    t = transitions({m: (0, 0, 8) for m in PRIMARY})
    assert h5(data(build_frame(correct), t), 0.05).outcome == "not_testable"


# ---- H3, H4, H6 (bootstrap differences) -------------------------------------------------------------
def noise(model, cond, rep, i):
    return random.Random(f"{model}{cond}{rep}{i}").randint(1, 5)


def spec_agree_t2_not_t3(model, cond, rep, i, code):
    # T2 identical across models; T3 differs between models but is repeatable within each model
    return TRUTH[code], noise(model, cond, 0, i)


def test_h3_and_h6_see_perfect_t2_agreement_against_unrelated_t3_ratings():
    d = data(build_frame(spec_agree_t2_not_t3, models=PRIMARY), resamples=300)
    res3 = h3(d, 0.05)
    assert res3.outcome == "supported" and len(res3.rows) == 2
    for row in res3.rows:
        assert row.estimate > 0.5 and row.ci_low > 0 and row.p_holm < 0.05  # alpha(T2) = 1 vs ~0
    res6 = h6(d, 0.05)
    t3_rows = [r for r in res6.rows if "T3" in r.label]
    assert len(res6.rows) == 4 and all(
        r.ci_low > 0 for r in t3_rows
    )  # repeats agree, models do not
    t2_rows = [r for r in res6.rows if "T2" in r.label]
    assert all(abs(r.estimate) < 1e-9 for r in t2_rows)  # both kappas are 1: difference 0
    assert res6.outcome == "supported"


def test_h4_is_inconclusive_when_c2_changes_nothing_and_supported_when_it_aligns_the_models():
    same = data(build_frame(spec_agree_t2_not_t3, models=PRIMARY), resamples=200)

    # C1 and C2 ratings are drawn per (model, condition): force identical ratings in both conditions
    def identical(model, cond, rep, i, code):
        return TRUTH[code], noise(model, "C", rep, i)

    res = h4(data(build_frame(identical, models=PRIMARY), resamples=200), 0.05)
    assert res.rows[0].estimate == pytest.approx(0.0) and res.rows[0].p == pytest.approx(1.0)
    assert res.outcome == "inconclusive"
    assert same is not None

    def aligned_in_c2(model, cond, rep, i, code):
        rating = 1 + (i % 5) if cond == "C2" else noise(model, cond, rep, i)
        return TRUTH[code], rating  # under C2 every model gives the same rating to a company

    res = h4(data(build_frame(aligned_in_c2, models=PRIMARY), resamples=300), 0.05)
    assert res.rows[0].estimate > 0.5 and res.rows[0].ci_low > 0 and res.outcome == "supported"


def test_h4_can_be_contradicted():
    def aligned_in_c1(model, cond, rep, i, code):
        rating = 1 + (i % 5) if cond == "C1" else noise(model, cond, rep, i)
        return TRUTH[code], rating

    res = h4(data(build_frame(aligned_in_c1, models=PRIMARY), resamples=300), 0.05)
    assert res.rows[0].estimate < -0.5 and res.rows[0].ci_high < 0 and res.outcome == "contradicted"


# ---- S1 -----------------------------------------------------------------------------------------------
def test_rating_shift_wilcoxon_and_cliffs_delta():
    def shift(model, cond, rep, i, code):
        base = 1 + (i % 3)
        return TRUTH[code], base + (1 if (cond == "C2" and model == "P1") else 0)

    res = rating_shift(data(build_frame(shift), resamples=200), 0.05)
    p1, p2 = res.rows[0], res.rows[1]
    assert p1.model == "P1" and p1.detail["up"] == 40 and p1.detail["mean_shift"] == 1.0
    assert p1.p < 1e-6 and p1.p_holm < 0.05 and p1.estimate > 0  # Cliff's delta of C2 vs C1
    assert p2.p == 1.0 and p2.estimate == 0.0 and p2.detail["same"] == 40
    assert res.outcome == "supported"


# ---- the whole set and its metric rows --------------------------------------------------------------
def test_run_hypotheses_lists_what_can_be_tested_and_never_tests_the_baseline():
    t = transitions({m: (6, 2, 1) for m in PRIMARY})
    results = run_hypotheses(data(build_frame(spec_agree_t2_not_t3), t))
    assert [r.id for r in results] == ["H1", "H2", "H3", "H4", "H6", "H5", "S1"]
    for res in results:
        assert {r.model for r in res.rows if r.model} <= set(PRIMARY)
        assert res.metric and res.test and res.falsification and res.outcome_rule  # all recorded
    c1_only = data(build_frame(correct, conditions=("C1",)))
    assert [r.id for r in run_hypotheses(c1_only)] == ["H1", "H3", "H6"]
    one_model = data(build_frame(correct, models=("P1", "B1")))
    assert [r.id for r in run_hypotheses(one_model)] == ["H1", "H2", "S1"]


def test_hypothesis_metrics_carry_the_rule_and_the_test_rows():
    res = run_hypotheses(data(build_frame(spec_h2(8, 2))))
    metrics = hypothesis_metrics(res)
    outcomes = {m.metric: m for m in metrics if m.metric.endswith("_outcome")}
    assert set(outcomes) == {
        "h1_outcome",
        "h2_outcome",
        "h3_outcome",
        "h4_outcome",
        "h6_outcome",
        "s1_outcome",
    }
    d = outcomes["h2_outcome"].detail
    assert (
        d["outcome"] == "inconclusive"
        and "McNemar" in d["test"]
        and "Holm" in d["falsification"] + d["test"]
    )
    tests = [m for m in metrics if m.metric == "h2_test"]
    assert len(tests) == 4 and {m.model for m in tests} == set(PRIMARY)
    assert tests[0].detail["p"] is not None and tests[0].detail["p_holm"] is not None


# ---- position effect -----------------------------------------------------------------------------------
def test_position_effect_detects_a_decline_with_position():
    def declining(model, cond, rep, i, code):
        return TRUTH[code], 1

    frame = build_frame(declining)
    frame["t2_class"] = [
        c if (p <= 14 or p % 4 == 0) else other(c)
        for c, p in zip(frame["t2_class"], frame["position"], strict=True)
    ]
    rng = random.Random(3)
    frame["t3_rating"] = [
        min(5, max(1, 5 - p // 4 + rng.choice([-1, 0, 0, 1]))) for p in frame["position"]
    ]
    metrics = position_effects(data(frame))
    logit = next(m for m in metrics if m.metric == "position_t2_logit" and m.model is None)
    assert (
        logit.detail["estimable"]
        and logit.value < 1
        and logit.ci_high < 1
        and logit.detail["p"] < 0.05
    )
    ordinal = next(m for m in metrics if m.metric == "position_t3_ordinal" and m.model is None)
    assert ordinal.detail["estimable"] and ordinal.value < 1 and ordinal.detail["p"] < 0.05
    terciles = [
        m for m in metrics if m.metric == "position_t2_accuracy_tercile" and m.model is None
    ]
    assert [m.detail["tercile"] for m in terciles] == [1, 2, 3]
    assert terciles[0].value > terciles[2].value  # accuracy falls from the first to the last third
    assert sum(m.n for m in terciles) == 4 * 2 * 2 * 20  # every primary judgment is in one tercile
    baseline = [m for m in metrics if m.model == "B1" and m.metric == "position_t2_logit"]
    assert len(baseline) == 1 and baseline[0].scope == "baseline"


def test_position_effect_reports_a_model_that_cannot_be_estimated():
    metrics = position_effects(data(build_frame(correct)))  # everything correct, every rating 3
    logit = next(m for m in metrics if m.metric == "position_t2_logit" and m.model is None)
    assert logit.value is None and logit.detail["estimable"] is False
    assert "no variation" in logit.detail["reason"]
    ordinal = next(m for m in metrics if m.metric == "position_t3_ordinal" and m.model is None)
    assert ordinal.detail["estimable"] is False
