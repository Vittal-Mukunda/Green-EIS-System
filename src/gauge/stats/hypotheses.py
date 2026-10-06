"""Hypotheses H1-H6 (spec §5). Each records its metric, its test and its falsification condition, and
the result is reported mechanically against that condition: no interpretation is attached.

This is a pilot (20 companies, 2 repetitions, 4 models): every test is exploratory. Units are
company judgments that are correlated (the same company appears in both repetitions and conditions),
so p-values are indicative only. Holm's correction is applied within each family of tests; the
controlled baseline (one model) is never entered into a test.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy import stats as sps

from gauge.evaluate.agreement import alpha_between, kappa_between, kappa_within
from gauge.evaluate.metrics import EvalData
from gauge.evaluate.results import Metric
from gauge.stats.primitives import (
    NAN,
    binomial_greater,
    bootstrap_ci,
    cliffs_delta,
    clopper_pearson,
    exact_mcnemar,
    holm,
    paired_odds_ratio,
)


@dataclass
class HRow:
    label: str  # model key, condition, or both
    estimate: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    p: float | None = None
    p_holm: float | None = None
    n: int | None = None
    model: str | None = None
    condition: str | None = None
    detail: dict = field(default_factory=dict)


@dataclass
class HypothesisResult:
    id: str
    statement: str
    metric: str
    test: str
    falsification: str
    rows: list[HRow]
    outcome: str  # supported | not_supported | contradicted | inconclusive | not_testable
    outcome_rule: str
    note: str = ""


def _apply_holm(rows: list[HRow]) -> None:
    adjusted = holm([r.p if r.p is not None else NAN for r in rows])
    for row, p in zip(rows, adjusted, strict=True):
        row.p_holm = None if math.isnan(p) else p


def _ci_outcome(rows: list[HRow], alpha: float, positive: bool = True) -> str:
    """supported if some row's interval excludes 0 on the hypothesised side (and its Holm p is below
    alpha), contradicted if some excludes it on the other side and none supports, else inconclusive."""
    if not rows or all(r.estimate is None for r in rows):
        return "not_testable"
    sup = [
        r for r in rows if r.ci_low is not None and (r.ci_low > 0 if positive else r.ci_high < 0)
    ]
    sup = [r for r in sup if r.p_holm is None or r.p_holm < alpha]
    if sup:
        return "supported"
    opp = [
        r for r in rows if r.ci_high is not None and (r.ci_high < 0 if positive else r.ci_low > 0)
    ]
    return "contradicted" if opp else "inconclusive"


# ---- H1 --------------------------------------------------------------------------------------------
def h1(d: EvalData) -> HypothesisResult:
    rows = []
    for model in d.primary:
        for cond in d.conditions:
            sub = d.ok[(d.ok["model_key"] == model) & (d.ok["condition"] == cond)]
            n, k = len(sub), int(sub["correct"].sum())
            low, high = clopper_pearson(k, n, d.ci) if n else (NAN, NAN)
            rows.append(
                HRow(
                    f"{model} {cond}",
                    k / n if n else None,
                    low,
                    high,
                    None,
                    None,
                    n,
                    model,
                    cond,
                    {"correct": k, "errors": n - k},
                )
            )
    observed = [r for r in rows if r.n and r.detail["errors"] > 0]
    return HypothesisResult(
        "H1",
        "T2 accuracy is below 100% for at least one model: the models are imperfect rule appliers.",
        "t2_accuracy",
        "exact (Clopper-Pearson) binomial interval per model and condition",
        "Every primary model classifies every company correctly in every condition and repetition.",
        rows,
        "supported" if observed else ("not_supported" if rows else "not_testable"),
        "supported if at least one primary model has at least one T2 error; no p-value (accuracy = 100% "
        "is refuted by any single error)",
    )


# ---- H2 --------------------------------------------------------------------------------------------
def h2(d: EvalData, alpha: float) -> HypothesisResult:
    key = ["model_key", "repetition", "company_code"]
    c1 = d.ok[d.ok["condition"] == "C1"].set_index(key)
    c2 = d.ok[d.ok["condition"] == "C2"].set_index(key)
    shared = c1.index.intersection(c2.index)
    rows = []
    for model in d.primary:
        idx = [i for i in shared if i[0] == model]
        if not idx:
            continue
        right1 = np.array([bool(c1.loc[i, "correct"]) for i in idx])
        right2 = np.array([bool(c2.loc[i, "correct"]) for i in idx])
        changed = sum(c1.loc[i, "t2_class"] != c2.loc[i, "t2_class"] for i in idx)
        b = int((right1 & ~right2).sum())  # correct under C1, wrong under C2
        c = int((~right1 & right2).sum())
        odds, low, high = paired_odds_ratio(b, c, d.ci)
        rows.append(
            HRow(
                model,
                odds if math.isfinite(odds) else None,
                low if math.isfinite(low) else None,
                high if math.isfinite(high) else None,
                exact_mcnemar(b, c),
                None,
                len(idx),
                model,
                None,
                {
                    "b_correct_to_wrong": b,
                    "c_wrong_to_correct": c,
                    "class_changed": int(changed),
                    "distortion_rate": changed / len(idx),
                    "odds_ratio_infinite": odds == math.inf,
                },
            )
        )
    _apply_holm(rows)
    observed = any(r.detail["class_changed"] > 0 for r in rows)
    significant = any(
        r.p_holm is not None
        and r.p_holm < alpha
        and r.detail["b_correct_to_wrong"] > r.detail["c_wrong_to_correct"]
        for r in rows
    )
    return HypothesisResult(
        "H2",
        "T2 class changes between C1 and C2 for at least one model (context distortion > 0).",
        "t2_context_distortion (and the change in correctness)",
        "exact McNemar test on correct/wrong under C1 vs C2 per model (pairs = repetition x company); "
        "Holm across models; odds ratio b/c with an exact interval",
        "No primary model changes any T2 class from C1 to C2 (distortion = 0), or no model shows a "
        "Holm-adjusted significant fall in correctness.",
        rows,
        "supported"
        if significant
        else ("inconclusive" if observed else ("not_supported" if rows else "not_testable")),
        f"supported if some model's Holm-adjusted McNemar p < {alpha} with more correct-to-wrong than "
        "wrong-to-correct pairs; inconclusive if classes change but no test is significant; "
        "not_supported if no class ever changes",
        note="Odds ratio = b/c; 'infinite' when no pair moved from wrong to correct.",
    )


# ---- bootstrap difference tests (H3, H4, H6) --------------------------------------------------------
def _difference(d: EvalData, label: str, fn, *, condition=None, detail=None) -> HRow:
    n_units = len(d.companies)
    boot = bootstrap_ci(fn, n_units, resamples=d.resamples, seed=d.seed, confidence=d.ci, null=0.0)
    p = None if math.isnan(boot.p_value) else boot.p_value
    return HRow(
        label,
        boot.estimate,
        boot.low,
        boot.high,
        p,
        None,
        n_units,
        None,
        condition,
        {"resamples": boot.resamples, "n_valid_resamples": boot.n_valid, **(detail or {})},
    )


def h3(d: EvalData, alpha: float) -> HypothesisResult:
    rows = []
    for cond in d.conditions:
        r = d.ratings(cond)
        rows.append(
            _difference(
                d,
                f"alpha(T2) - alpha(T3), {cond}",
                lambda idx, r=r: alpha_between(r, "t2", idx) - alpha_between(r, "t3", idx),
                condition=cond,
            )
        )
    _apply_holm(rows)
    return HypothesisResult(
        "H3",
        "Agreement between models on T2 is higher than on T3.",
        "t2_between_alpha_nominal minus t3_between_alpha_ordinal, per condition",
        "percentile bootstrap (resampling companies) of the difference of the two alphas; two-sided "
        "bootstrap p; Holm across the conditions",
        "In every condition the 95% interval of alpha(T2) - alpha(T3) includes 0 or lies below it.",
        rows,
        _ci_outcome(rows, alpha),
        "supported if some condition's interval lies above 0 (Holm-adjusted p below alpha); contradicted "
        "if an interval lies wholly below 0 and none supports; otherwise inconclusive",
        note="Nominal and ordinal alphas are on different scales; the difference is a descriptive contrast.",
    )


def h4(d: EvalData, alpha: float) -> HypothesisResult:
    rows = []
    if {"C1", "C2"} <= set(d.conditions):
        r1, r2 = d.ratings("C1"), d.ratings("C2")
        rows.append(
            _difference(
                d,
                "alpha(T3, C2) - alpha(T3, C1)",
                lambda idx: alpha_between(r2, "t3", idx) - alpha_between(r1, "t3", idx),
            )
        )
    _apply_holm(rows)
    return HypothesisResult(
        "H4",
        "Agreement between models on T3 is higher under C2 than under C1 (null-tolerant).",
        "t3_between_alpha_ordinal, C2 minus C1",
        "percentile bootstrap (resampling companies, the same companies in both conditions) of the "
        "difference of the two alphas",
        "The 95% interval of the difference includes 0 or lies below it. A null result is reported as "
        "such, not as evidence against context.",
        rows,
        _ci_outcome(rows, alpha),
        "supported if the interval lies above 0; contradicted if wholly below 0; otherwise inconclusive",
    )


# ---- H5 ------------------------------------------------------------------------------------------------
def h5(d: EvalData, alpha: float) -> HypothesisResult:
    t = d.transitions[d.transitions["model_key"].isin(d.primary)]
    rows = []
    for model in d.primary:
        m = t[t["model_key"] == model]
        consistent = int(((m["label"] == "consistent") & (m["expected"] != "none")).sum())
        violating = int((m["label"] == "violating").sum())
        n = consistent + violating
        rows.append(
            HRow(
                model,
                consistent / n if n else None,
                *(clopper_pearson(consistent, n, d.ci) if n else (None, None)),
                binomial_greater(consistent, n) if n else None,
                None,
                n,
                model,
                None,
                {
                    "consistent": consistent,
                    "violating": violating,
                    "unconstrained": int((m["label"] == "unconstrained").sum()),
                },
            )
        )
    _apply_holm(rows)
    k = sum(r.detail["consistent"] for r in rows)
    v = sum(r.detail["violating"] for r in rows)
    pooled = HRow(
        "all primary models (pooled)",
        k / (k + v) if k + v else None,
        *(clopper_pearson(k, k + v, d.ci) if k + v else (None, None)),
        binomial_greater(k, k + v) if k + v else None,
        None,
        k + v,
        None,
        None,
        {"consistent": k, "violating": v, "headline": True},
    )
    pooled.p_holm = pooled.p
    if not rows or (k + v) == 0:
        outcome = "not_testable"
    else:
        outcome = "supported" if pooled.p is not None and pooled.p < alpha else "not_supported"
    return HypothesisResult(
        "H5",
        "C1 to C2 rating changes are rule-consistent more often than they are violating.",
        "t3_consistent_rate vs t3_violating_rate on the constrained transitions",
        "one-sided exact binomial test (consistent vs violating, H0: 0.5) on the pooled primary panel "
        "(headline) and per model with Holm across models",
        "Among transitions with an expected direction, consistent changes are not more frequent than "
        "violating ones (pooled one-sided p >= alpha).",
        [pooled, *rows],
        outcome,
        f"supported if the pooled one-sided p < {alpha}",
        note="A transition with an unchanged rating is 'consistent' when a direction is expected; "
        "unconstrained transitions are excluded from the test.",
    )


# ---- H6 ------------------------------------------------------------------------------------------------
def h6(d: EvalData, alpha: float) -> HypothesisResult:
    rows = []
    for cond in d.conditions:
        r = d.ratings(cond)
        for which, name in (("t2", "T2"), ("t3", "T3")):
            rows.append(
                _difference(
                    d,
                    f"within-model kappa - between-model kappa, {name}, {cond}",
                    lambda idx, r=r, w=which: kappa_within(r, w, idx) - kappa_between(r, w, idx),
                    condition=cond,
                    detail={
                        "scale": "nominal kappa" if which == "t2" else "quadratic weighted kappa"
                    },
                )
            )
    _apply_holm(rows)
    return HypothesisResult(
        "H6",
        "Within-model repeatability is higher than between-model agreement.",
        "t2/t3 within-model kappa (repetition 1 vs 2, mean over models) minus between-model kappa "
        "(mean over model pairs and repetitions)",
        "percentile bootstrap over companies of the difference; two-sided bootstrap p; Holm across the "
        "four tests (T2/T3 x C1/C2)",
        "In every test the 95% interval of the difference includes 0 or lies below it.",
        rows,
        _ci_outcome(rows, alpha),
        "supported if some interval lies above 0 with Holm-adjusted p below alpha; contradicted if some "
        "lies wholly below 0 and none supports; otherwise inconclusive",
        note="Both quantities are Cohen's kappa over pairs of rating vectors, so they share a scale.",
    )


# ---- supplementary: rating shift ------------------------------------------------------------------------
def rating_shift(d: EvalData, alpha: float) -> HypothesisResult:
    """Not one of H1-H6: the paired C1 -> C2 change of the T3 rating per primary model."""
    key = ["model_key", "repetition", "company_code"]
    c1 = d.ok[d.ok["condition"] == "C1"].set_index(key)
    c2 = d.ok[d.ok["condition"] == "C2"].set_index(key)
    shared = c1.index.intersection(c2.index)
    rows = []
    for model in d.primary:
        idx = [i for i in shared if i[0] == model]
        if len(idx) < 2:
            continue
        a = np.array([int(c1.loc[i, "t3_rating"]) for i in idx], dtype=float)
        b = np.array([int(c2.loc[i, "t3_rating"]) for i in idx], dtype=float)
        codes = np.array([i[2] for i in idx])
        diff = b - a
        try:
            p = float(sps.wilcoxon(b, a, zero_method="wilcox").pvalue) if np.any(diff != 0) else 1.0
        except ValueError:
            p = None
        companies = sorted(set(codes))

        def delta(unit_idx, a=a, b=b, codes=codes, companies=companies):
            chosen = [companies[i] for i in unit_idx]
            mask = np.concatenate([np.where(codes == c)[0] for c in chosen])
            return cliffs_delta(b[mask], a[mask])

        boot = bootstrap_ci(
            delta, len(companies), resamples=d.resamples, seed=d.seed, confidence=d.ci
        )
        rows.append(
            HRow(
                model,
                cliffs_delta(b, a),
                boot.low,
                boot.high,
                p,
                None,
                len(idx),
                model,
                None,
                {
                    "mean_shift": float(diff.mean()),
                    "up": int((diff > 0).sum()),
                    "down": int((diff < 0).sum()),
                    "same": int((diff == 0).sum()),
                },
            )
        )
    _apply_holm(rows)
    return HypothesisResult(
        "S1",
        "Supplementary: the T3 rating changes between C1 and C2 (paired, within company and repetition).",
        "t3_mean_rating_shift; Cliff's delta of C2 vs C1 ratings",
        "Wilcoxon signed-rank test per model (zero differences dropped), Holm across models; Cliff's "
        "delta with a company bootstrap interval",
        "No model's ratings differ between C1 and C2 (Holm-adjusted p >= alpha for every model).",
        rows,
        "supported"
        if any(r.p_holm is not None and r.p_holm < alpha for r in rows)
        else ("not_supported" if rows else "not_testable"),
        "supported if some model has a Holm-adjusted Wilcoxon p below alpha",
    )


# ---- all of them ------------------------------------------------------------------------------------------
def run_hypotheses(d: EvalData, alpha: float = 0.05) -> list[HypothesisResult]:
    out = [h1(d)]
    if {"C1", "C2"} <= set(d.conditions):
        out.append(h2(d, alpha))
    if len(d.primary) >= 2:
        out.append(h3(d, alpha))
        if {"C1", "C2"} <= set(d.conditions):
            out.append(h4(d, alpha))
        if len(d.reps) >= 2:
            out.append(h6(d, alpha))
    if not d.transitions.empty:
        out.append(h5(d, alpha))
    if {"C1", "C2"} <= set(d.conditions):
        out.append(rating_shift(d, alpha))
    return out


def hypothesis_metrics(results: list[HypothesisResult]) -> list[Metric]:
    """The test rows as Metric rows (`h<k>_test`), plus one outcome row per hypothesis."""
    out: list[Metric] = []
    for res in results:
        out.append(
            Metric(
                f"{res.id.lower()}_outcome",
                "panel",
                value=None,
                detail={
                    "outcome": res.outcome,
                    "statement": res.statement,
                    "metric": res.metric,
                    "test": res.test,
                    "falsification": res.falsification,
                    "outcome_rule": res.outcome_rule,
                    "note": res.note,
                },
            )
        )
        for row in res.rows:
            out.append(
                Metric(
                    f"{res.id.lower()}_test",
                    "model" if row.model else ("condition" if row.condition else "panel"),
                    value=row.estimate,
                    model=row.model,
                    condition=row.condition,
                    ci_low=row.ci_low,
                    ci_high=row.ci_high,
                    n=row.n,
                    detail={"label": row.label, "p": row.p, "p_holm": row.p_holm, **row.detail},
                )
            )
    return out
