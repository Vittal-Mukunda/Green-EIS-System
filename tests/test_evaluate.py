"""`gauge evaluate` end to end on crafted replies.

Each model's behaviour is defined by a few rules below, so every expected number is derived from those
rules by plain loops, independently of the evaluation code.
"""

from __future__ import annotations

from decimal import Decimal

import krippendorff
import numpy as np
import pytest
from sqlalchemy import func, select

from gauge.db.models import (
    Claim,
    DisagreementFlag,
    EvaluationResult,
    Judgment,
    Run,
    TransitionResult,
)
from gauge.db.session import session_scope
from gauge.evaluate.results import EVAL_VERSION, STATS_VERSION, load_metrics
from gauge.evaluate.run import EvaluationError, run_evaluation
from gauge.evaluate.standards import load_standards
from gauge.render.prompts import num
from gauge.render.runs import render_run_prompts
from gauge.rules.rounding import sig_round
from gauge.runcmd import stage_parse
from gauge.runner.execute import execute_run
from gauge.stats.run import run_statistics
from gauge.vocab import T2_CLASSES
from helpers import CannedRunner, good_item

PRIMARY = ["P1", "P2", "P3", "P4"]


def other(cls):
    return T2_CLASSES[(T2_CLASSES.index(cls) + 1) % 3]


class Scenario:
    """Who says what. `i` is the company's index in sorted code order."""

    def __init__(self, std, evidence, ind):
        self.std, self.ev, self.ind = std, evidence, ind
        self.codes = sorted(std.t2)
        self.truth = {c: std.t2[c].t2_class for c in self.codes}

    def cls(self, model, cond, rep, i):
        truth = self.truth[self.codes[i]]
        wrong = (
            (model == "P2" and cond == "C2" and i == 0)
            or (model == "P3" and rep == 2 and i == 1)
            or (model == "B1" and cond == "C1" and rep == 1 and i == 2)
        )
        return other(truth) if wrong else truth

    def rating(self, model, cond, rep, i):
        if model == "P2":
            return 3 if cond == "C1" else 4
        if model == "P3":
            return 3 if (rep == 2 and i == 1) else 2
        if model == "B1":
            return 2
        if model == "P4" and cond == "C2":
            return 3 + {"up": 1, "down": -1, "none": 0}[self.std.t3[self.codes[i]].expected]
        return 3

    def justification(self, model, cond, i):
        ce = self.ev.companies[self.codes[i]]
        value = ce.kpis["water_intensity"]
        if model == "P1":
            return f"Water intensity is {num(value)}."
        if model == "P2":
            if cond == "C1":
                return f"Water intensity is {num(value)}."
            return f"Water intensity is {num(sig_round(value * Decimal('1.05'), 4))}."  # a misquote
        if model == "P4":
            return f"Water intensity was {num(ce.trend['water_intensity']['FY2022-23'])} in the first year."
        return "Total energy consumption looks high."


@pytest.fixture
def scenario(world, ctx):
    with session_scope(world.engine) as s:
        std = load_standards(s, world.cfg, world.ind)
    sc = Scenario(std, std.evidence, world.ind)
    directions = {sc.std.t3[c].expected for c in sc.codes}
    assert directions & {"up", "down"}, "the synthetic sample must have a constrained transition"
    return sc


def replies(world, ctx, sc, *, break_company=None):
    labels = world.ind.driver_labels[:3]
    plan = render_run_prompts(world.cfg, world.ind, world.models, ctx)
    out = {}
    for rp in plan:
        p = rp.planned
        items = []
        for code in p.company_order:
            i = sc.codes.index(code)
            item = good_item(code, labels)
            item["t2_class"] = sc.cls(p.model_key, p.condition, p.repetition, i)
            item["t3_rating"] = sc.rating(p.model_key, p.condition, p.repetition, i)
            item["justification"] = sc.justification(p.model_key, p.condition, i)
            if break_company == (p.run_id, i):
                item["t3_rating"] = 99  # invalid: stays a parse failure (no repair is made)
            items.append(item)
        out[p.run_id] = items
    return plan, out


@pytest.fixture
def evaluated(world, ctx, scenario):
    plan, canned = replies(world, ctx, scenario)
    runner = CannedRunner(canned)
    with session_scope(world.engine) as s:
        for rp in plan:
            prompt, system = rp.prompt.for_channel("cursor")
            execute_run(s, world.cfg, runner, rp.planned, prompt, system_prompt=system)
    assert stage_parse(world.engine, world.cfg, world.ind).status == "ok"
    with session_scope(world.engine) as s:
        summary = run_evaluation(s, world.cfg, world.ind)
    with session_scope(world.engine) as s:
        metrics = load_metrics(s, EVAL_VERSION)
    return SimpleNamespaceExt(world=world, sc=scenario, summary=summary, metrics=metrics)


class SimpleNamespaceExt:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def get(self, metric, model=None, condition=None):
        found = [
            m
            for m in self.metrics
            if m.metric == metric and m.model == model and m.condition == condition
        ]
        assert len(found) == 1, (metric, model, condition, len(found))
        return found[0]


MODELS = ["B1", *PRIMARY]


# ---- summary ---------------------------------------------------------------------------------------
def test_the_summary_counts(evaluated):
    s = evaluated.summary
    assert (s.judgments, s.valid) == (
        120,
        120,
    )  # 5 models x 2 conditions x 2 repetitions x 6 companies
    assert s.transitions == 60 and s.claims > 0 and s.metrics == len(evaluated.metrics)


# ---- T2 accuracy, distortion, repeatability ---------------------------------------------------------
def test_t2_accuracy_per_model_and_condition(evaluated):
    sc = evaluated.sc
    for model in MODELS:
        for cond in ("C1", "C2"):
            k = sum(
                sc.cls(model, cond, r, i) == sc.truth[sc.codes[i]] for r in (1, 2) for i in range(6)
            )
            m = evaluated.get("t2_accuracy", model, cond)
            assert (m.value, m.n, m.detail["k"]) == (pytest.approx(k / 12), 12, k)
            assert m.ci_low < m.value < m.ci_high or k in (0, 12)
            assert evaluated.get("valid_share", model, cond).value == 1.0
    assert evaluated.get("t2_accuracy", "P1", "C1").value == 1.0
    assert evaluated.get("t2_accuracy", "P2", "C2").value == pytest.approx(10 / 12)
    assert evaluated.get("t2_accuracy", "P3", "C1").value == pytest.approx(11 / 12)


def test_context_distortion_counts_class_changes_between_conditions(evaluated):
    sc = evaluated.sc
    for model in MODELS:
        changed = sum(
            sc.cls(model, "C1", r, i) != sc.cls(model, "C2", r, i) for r in (1, 2) for i in range(6)
        )
        m = evaluated.get("t2_context_distortion", model)
        assert (m.detail["k"], m.n) == (changed, 12)
    assert evaluated.get("t2_context_distortion", "P2").detail["k"] == 2
    assert (
        evaluated.get("t2_context_distortion", "P3").detail["k"] == 0
    )  # wrong the same way in both
    assert evaluated.get("t2_context_distortion", "B1").detail["k"] == 1


def test_repeatability_between_repetitions(evaluated):
    sc = evaluated.sc
    for model in MODELS:
        for cond in ("C1", "C2"):
            same_t2 = sum(sc.cls(model, cond, 1, i) == sc.cls(model, cond, 2, i) for i in range(6))
            same_t3 = sum(
                sc.rating(model, cond, 1, i) == sc.rating(model, cond, 2, i) for i in range(6)
            )
            assert evaluated.get("t2_repeatability_agreement", model, cond).detail["k"] == same_t2
            assert evaluated.get("t3_repeatability_exact", model, cond).detail["k"] == same_t3
    assert evaluated.get("t2_repeatability_agreement", "P3", "C1").value == pytest.approx(5 / 6)
    assert evaluated.get("t2_repeatability_agreement", "P1", "C2").value == 1.0
    assert evaluated.get("t3_repeatability_exact", "P3", "C2").value == pytest.approx(5 / 6)


def test_t3_means(evaluated):
    sc = evaluated.sc
    for model in MODELS:
        for cond in ("C1", "C2"):
            ratings = [sc.rating(model, cond, r, i) for r in (1, 2) for i in range(6)]
            assert evaluated.get("t3_mean_rating", model, cond).value == pytest.approx(
                np.mean(ratings)
            )
    shift = evaluated.get("t3_mean_rating_shift", "P2")
    assert shift.value == pytest.approx(1.0) and shift.detail["up"] == 12


# ---- attribute agreement -------------------------------------------------------------------------------
def test_msa_percentages(evaluated):
    sc = evaluated.sc
    for model in PRIMARY:
        for cond in ("C1", "C2"):
            within = sum(sc.cls(model, cond, 1, i) == sc.cls(model, cond, 2, i) for i in range(6))
            vs_std = sum(
                all(sc.cls(model, cond, r, i) == sc.truth[sc.codes[i]] for r in (1, 2))
                for i in range(6)
            )
            assert evaluated.get("msa_within_appraiser", model, cond).detail["k"] == within
            assert evaluated.get("msa_vs_standard", model, cond).detail["k"] == vs_std
    for cond, expected in (("C1", 5), ("C2", 4)):
        identical = sum(
            len({sc.cls(m, cond, r, i) for m in PRIMARY for r in (1, 2)}) == 1 for i in range(6)
        )
        assert identical == expected
        between = evaluated.get("msa_between_appraisers", None, cond)
        assert (between.detail["k"], between.n) == (expected, 6)
        assert evaluated.get("msa_all_vs_standard", None, cond).detail["k"] == expected
    assert evaluated.get("msa_kappa_vs_standard", "P1", "C1").value == pytest.approx(1.0)
    assert (
        evaluated.get("msa_within_appraiser", "B1", "C1").detail["k"] == 5
    )  # the baseline is scored too


def test_between_model_alpha_equals_an_independent_calculation(evaluated):
    sc = evaluated.sc
    for cond in ("C1", "C2"):
        mats = {
            r: np.array(
                [[T2_CLASSES.index(sc.cls(m, cond, r, i)) for i in range(6)] for m in PRIMARY],
                float,
            )
            for r in (1, 2)
        }
        expected = np.mean(
            [
                krippendorff.alpha(reliability_data=mats[r], level_of_measurement="nominal")
                for r in (1, 2)
            ]
        )
        metric = evaluated.get("t2_between_alpha_nominal", None, cond)
        assert metric.value == pytest.approx(expected)
        assert metric.ci_low <= metric.value <= metric.ci_high or metric.ci_low is None
        assert metric.detail["models"] == PRIMARY  # the baseline is never pooled
        t3 = {
            r: np.array([[sc.rating(m, cond, r, i) for i in range(6)] for m in PRIMARY], float)
            for r in (1, 2)
        }
        t3_expected = np.nanmean(
            [
                krippendorff.alpha(reliability_data=t3[r], level_of_measurement="ordinal")
                if len(np.unique(t3[r])) > 1
                else np.nan
                for r in (1, 2)
            ]
        )
        assert evaluated.get("t3_between_alpha_ordinal", None, cond).value == pytest.approx(
            t3_expected
        )


# ---- the T3 update rule -----------------------------------------------------------------------------------
def test_transition_labels_follow_the_update_rule(evaluated, world):
    sc = evaluated.sc
    expected = {c: sc.std.t3[c].expected for c in sc.codes}
    with session_scope(world.engine) as s:
        rows = list(s.scalars(select(TransitionResult)))
    assert len(rows) == 60 and {r.variant for r in rows} == {""}
    for model in MODELS:
        counts = {"consistent": 0, "violating": 0, "unconstrained": 0}
        for r in (1, 2):
            for i, code in enumerate(sc.codes):
                delta = sc.rating(model, "C2", r, i) - sc.rating(model, "C1", r, i)
                exp = expected[code]
                if exp == "none":
                    label = "unconstrained"
                elif (exp == "up" and delta >= 0) or (exp == "down" and delta <= 0):
                    label = "consistent"
                else:
                    label = "violating"
                counts[label] += 1
        for label, k in counts.items():
            assert evaluated.get(f"t3_{label}_rate", model).detail[label] == k, (model, label)
    p4 = evaluated.get("t3_violating_rate", "P4")
    assert p4.detail["violating"] == 0  # P4 moves every constrained rating the expected way
    n_down = sum(e == "down" for e in expected.values())
    assert evaluated.get("t3_violating_rate", "P2").detail["violating"] == 2 * n_down
    assert all(
        r.trend_signal in (-1, 0, 1) and r.expected_direction in ("up", "down", "none")
        for r in rows
    )


def test_flags(evaluated, world):
    sc = evaluated.sc
    n_down = sum(sc.std.t3[c].expected == "down" for c in sc.codes)
    with session_scope(world.engine) as s:
        grouped = s.execute(
            select(DisagreementFlag.flag_type, func.count()).group_by(DisagreementFlag.flag_type)
        ).all()
        counts = {kind: n for kind, n in grouped}
    assert counts["t2_flip"] == 2 + 1  # P2 (company 0, two repetitions) and B1 (one pair)
    assert counts["rule_violation"] == 2 * n_down
    assert counts["t2_models_disagree"] == 1 + 3  # C1: P3 in repetition 2; C2: P2 twice, P3 once
    with session_scope(world.engine) as s:
        detail = (
            s.scalars(select(DisagreementFlag).where(DisagreementFlag.flag_type == "t2_flip"))
            .first()
            .detail
        )
    assert set(detail) == {"C1", "C2", "rule_class"}


# ---- grounding -----------------------------------------------------------------------------
def test_grounding_rates(evaluated):
    for cond in ("C1", "C2"):
        assert evaluated.get("claims_supported", "P1", cond).value == 1.0
        assert evaluated.get("claims_wrong", "P1", cond).value == 0.0
    assert evaluated.get("claims_supported", "P2", "C1").value == 1.0
    wrong = evaluated.get("claims_wrong", "P2", "C2")
    assert wrong.value == 1.0 and wrong.n == 12  # a 5% misquote is "wrong", not "unsupported"
    assert evaluated.get("claims_supported", "P4", "C2").value == 1.0  # the trend value was shown
    assert evaluated.get("claims_supported", "P4", "C1").value < 1.0  # ... but not under C1
    p3 = evaluated.get("claims_supported", "P3", "C1")
    assert (
        p3.n == 0 and p3.value is None and p3.detail["pending_annotation"] == 12
    )  # no numbers: queued


def test_taxonomy_rows_use_t2_correctness_and_unsupported_claims(evaluated):
    p2 = evaluated.get("taxonomy_objective_error", "P2", "C2")
    assert p2.detail["k"] == 2
    unsupported = evaluated.get("taxonomy_unsupported_claim", "P2", "C2")
    assert (
        unsupported.detail["k"] == 10
    )  # correct T2 but a wrong numeric claim: the other 10 judgments


# ---- baseline comparison ---------------------------------------------------------------------
def test_baseline_comparison_is_descriptive_only(evaluated):
    row = evaluated.get("cmp_t2_accuracy", "B1", "C1")
    panel = [evaluated.get("t2_accuracy", m, "C1").value for m in PRIMARY]
    assert row.scope == "baseline" and row.value == pytest.approx(11 / 12 - np.mean(panel))
    assert row.detail["panel_models"] == 4 and row.detail["panel_min"] == min(panel)
    assert not [m for m in evaluated.metrics if m.metric.startswith("cmp_") and m.model != "B1"]


# ---- re-running and invalid judgments --------------------------------------------------------
def test_evaluating_again_changes_nothing_and_stats_rows_are_kept_apart(evaluated, world):
    with session_scope(world.engine) as s:
        claim_ids = sorted(s.scalars(select(Claim.id)))
        before = [(m.metric, m.model, m.condition, m.value) for m in load_metrics(s, EVAL_VERSION)]
        run_evaluation(s, world.cfg, world.ind)
    with session_scope(world.engine) as s:
        assert sorted(s.scalars(select(Claim.id))) == claim_ids  # claims keep their identity
        assert [
            (m.metric, m.model, m.condition, m.value) for m in load_metrics(s, EVAL_VERSION)
        ] == before
        assert s.scalar(select(func.count()).select_from(TransitionResult)) == 60
        run_statistics(s, world.cfg, world.ind)
    with session_scope(world.engine) as s:
        n_stats = s.scalar(
            select(func.count())
            .select_from(EvaluationResult)
            .where(EvaluationResult.eval_version == STATS_VERSION)
        )
        assert n_stats > 0
        run_evaluation(s, world.cfg, world.ind)  # evaluate must not delete the stats rows
        assert (
            s.scalar(
                select(func.count())
                .select_from(EvaluationResult)
                .where(EvaluationResult.eval_version == STATS_VERSION)
            )
            == n_stats
        )


def test_an_invalid_judgment_is_excluded_and_reported(world, ctx, scenario):
    plan, canned = replies(world, ctx, scenario)
    target = next(
        rp
        for rp in plan
        if rp.planned.model_key == "P1"
        and rp.planned.condition == "C1"
        and rp.planned.repetition == 1
    )
    _, canned = replies(world, ctx, scenario, break_company=(target.planned.run_id, 3))
    runner = CannedRunner(canned)
    with session_scope(world.engine) as s:
        for rp in plan:
            prompt, system = rp.prompt.for_channel("cursor")
            execute_run(s, world.cfg, runner, rp.planned, prompt, system_prompt=system)
    stage_parse(world.engine, world.cfg, world.ind)  # no repair is made: the company stays invalid
    with session_scope(world.engine) as s:
        summary = run_evaluation(s, world.cfg, world.ind)
        metrics = {(m.metric, m.model, m.condition): m for m in load_metrics(s, EVAL_VERSION)}
        invalid = s.scalar(
            select(func.count())
            .select_from(Judgment)
            .where(Judgment.parse_status == "parse_failure")
        )
    assert invalid == 1 and summary.valid == 119 and summary.transitions == 59
    share = metrics[("valid_share", "P1", "C1")]
    assert (share.detail["k"], share.n) == (11, 12)
    assert (
        metrics[("t2_accuracy", "P1", "C1")].n == 11
    )  # the invalid judgment is not in the denominator
    assert (
        metrics[("msa_within_appraiser", "P1", "C1")].n == 5
    )  # that company drops out of the cell


def test_evaluation_without_judgments_says_what_to_do(world, ctx):
    with session_scope(world.engine) as s, pytest.raises(EvaluationError, match="gauge parse"):
        run_evaluation(s, world.cfg, world.ind)


def test_evaluation_needs_the_rules(world):
    with session_scope(world.engine) as s, pytest.raises(EvaluationError):
        run_evaluation(s, world.cfg, world.ind)
    assert Run  # the module is used above; keeps the import honest
