"""The evaluation metrics of spec §5, as Metric rows (see evaluate/results.py for the row format).

Every number is computed from stored judgments and the frozen rules; there is no model in the scoring
loop. Units of analysis: one company judgment, identified by (model, condition, repetition, company).
Invalid judgments (still failing after the repair) are excluded from a metric, and the share that is
left out is reported as `valid_share`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from gauge.evaluate.agreement import (
    Ratings,
    alpha_between,
    build_ratings,
    fleiss_between,
    kappa_between,
    kappa_within,
)
from gauge.evaluate.results import Metric
from gauge.evaluate.standards import Standards
from gauge.msa.attribute import Agreement, attribute_agreement
from gauge.stats.primitives import (
    NAN,
    bootstrap_ci,
    clopper_pearson,
    cohen_kappa,
    krippendorff_alpha,
)
from gauge.vocab import T2_CLASSES

RATING_LABELS = [1, 2, 3, 4, 5]
SCORED_CLAIM_STATUSES = ("supported", "unsupported", "wrong")


@dataclass
class EvalData:
    frame: pd.DataFrame  # every judgment (valid flag)
    ok: pd.DataFrame  # valid judgments + truth_t2 + correct
    standards: Standards
    transitions: pd.DataFrame  # model_key, company_code, repetition, label, expected, delta, ...
    claims: pd.DataFrame  # model_key, condition, judgment_id, claim_type, status
    conditions: list[str]
    reps: list[int]
    roles: dict[str, str]  # model key -> primary | baseline | sensitivity
    companies: list[str]
    resamples: int
    seed: int
    ci: float

    @property
    def primary(self) -> list[str]:
        return sorted(m for m, r in self.roles.items() if r == "primary")

    def ratings(self, condition: str) -> Ratings:
        return build_ratings(self.ok, self.primary, condition, self.reps, self.companies)


def prepare(
    frame: pd.DataFrame,
    standards: Standards,
    transitions: pd.DataFrame,
    claims: pd.DataFrame,
    *,
    resamples: int,
    seed: int,
    ci: float,
) -> EvalData:
    ok = frame[frame["valid"]].copy()
    ok["truth_t2"] = ok["company_code"].map(lambda c: standards.t2[c].t2_class)
    ok["correct"] = ok["t2_class"] == ok["truth_t2"]
    roles = dict(zip(frame["model_key"], frame["role"], strict=True))
    return EvalData(
        frame=frame,
        ok=ok,
        standards=standards,
        transitions=transitions,
        claims=claims,
        conditions=sorted(frame["condition"].unique()),
        reps=sorted(int(r) for r in frame["repetition"].unique()),
        roles=roles,
        companies=sorted(standards.t2),
        resamples=resamples,
        seed=seed,
        ci=ci,
    )


def _proportion(
    name: str, scope: str, k: int, n: int, ci: float, *, model=None, condition=None, detail=None
) -> Metric:
    low, high = clopper_pearson(k, n, ci) if n else (NAN, NAN)
    return Metric(
        name,
        scope,
        value=k / n if n else None,
        model=model,
        condition=condition,
        ci_low=low,
        ci_high=high,
        n=n,
        detail={"k": k, **(detail or {})},
    )


# ---- one model, one condition ----------------------------------------------------------------------
def model_condition_metrics(d: EvalData) -> list[Metric]:
    out: list[Metric] = []
    for model in sorted(d.roles):
        role = d.roles[model]
        for cond in d.conditions:
            allrows = d.frame[(d.frame["model_key"] == model) & (d.frame["condition"] == cond)]
            if allrows.empty:
                continue
            sub = d.ok[(d.ok["model_key"] == model) & (d.ok["condition"] == cond)]
            extra = {"role": role}
            out.append(
                _proportion(
                    "valid_share",
                    "model_condition",
                    len(sub),
                    len(allrows),
                    d.ci,
                    model=model,
                    condition=cond,
                    detail=extra,
                )
            )
            out.append(
                _proportion(
                    "t2_accuracy",
                    "model_condition",
                    int(sub["correct"].sum()),
                    len(sub),
                    d.ci,
                    model=model,
                    condition=cond,
                    detail=extra,
                )
            )
            if len(sub):
                ratings = sub["t3_rating"].astype(float)
                counts = {int(r): int((ratings == r).sum()) for r in RATING_LABELS}
                out.append(
                    Metric(
                        "t3_mean_rating",
                        "model_condition",
                        value=ratings.mean(),
                        model=model,
                        condition=cond,
                        n=len(sub),
                        detail={
                            **extra,
                            "sd": ratings.std(ddof=1) if len(sub) > 1 else None,
                            "counts": counts,
                            "mean_confidence": float(sub["t3_confidence"].astype(float).mean()),
                        },
                    )
                )
            out += _repeatability(d, model, cond, sub, extra)
    return out


def _repeatability(
    d: EvalData, model: str, cond: str, sub: pd.DataFrame, extra: dict
) -> list[Metric]:
    if len(d.reps) < 2:
        return []
    first, second = d.reps[:2]
    a = sub[sub["repetition"] == first].set_index("company_code")
    b = sub[sub["repetition"] == second].set_index("company_code")
    shared = sorted(set(a.index) & set(b.index))
    n = len(shared)
    if n == 0:
        return []
    c1, c2 = a.loc[shared, "t2_class"].tolist(), b.loc[shared, "t2_class"].tolist()
    r1, r2 = (
        a.loc[shared, "t3_rating"].astype(int).tolist(),
        b.loc[shared, "t3_rating"].astype(int).tolist(),
    )
    out = [
        _proportion(
            "t2_repeatability_agreement",
            "model_condition",
            sum(x == y for x, y in zip(c1, c2, strict=True)),
            n,
            d.ci,
            model=model,
            condition=cond,
            detail=extra,
        ),
        Metric(
            "t2_repeatability_kappa",
            "model_condition",
            value=cohen_kappa(c1, c2, labels=list(T2_CLASSES)),
            model=model,
            condition=cond,
            n=n,
            detail=extra,
        ),
        _proportion(
            "t3_repeatability_exact",
            "model_condition",
            sum(x == y for x, y in zip(r1, r2, strict=True)),
            n,
            d.ci,
            model=model,
            condition=cond,
            detail=extra,
        ),
        Metric(
            "t3_repeatability_wkappa",
            "model_condition",
            value=cohen_kappa(r1, r2, weights="quadratic", labels=RATING_LABELS),
            model=model,
            condition=cond,
            n=n,
            detail={**extra, "weights": "quadratic"},
        ),
    ]
    return out


# ---- one model, across conditions --------------------------------------------------------------------
def model_metrics(d: EvalData) -> list[Metric]:
    out: list[Metric] = []
    if len(d.conditions) < 2 or "C1" not in d.conditions or "C2" not in d.conditions:
        return out
    key = ["model_key", "repetition", "company_code"]
    c1 = d.ok[d.ok["condition"] == "C1"].set_index(key)
    c2 = d.ok[d.ok["condition"] == "C2"].set_index(key)
    shared = c1.index.intersection(c2.index)
    for model in sorted(d.roles):
        extra = {"role": d.roles[model]}
        rows = [i for i in shared if i[0] == model]
        if rows:
            changed = sum(c1.loc[i, "t2_class"] != c2.loc[i, "t2_class"] for i in rows)
            out.append(
                _proportion(
                    "t2_context_distortion",
                    "model",
                    changed,
                    len(rows),
                    d.ci,
                    model=model,
                    detail=extra,
                )
            )
            shifts = [int(c2.loc[i, "t3_rating"]) - int(c1.loc[i, "t3_rating"]) for i in rows]
            out.append(
                Metric(
                    "t3_mean_rating_shift",
                    "model",
                    value=float(np.mean(shifts)),
                    model=model,
                    n=len(rows),
                    detail={
                        **extra,
                        "up": sum(s > 0 for s in shifts),
                        "down": sum(s < 0 for s in shifts),
                        "same": sum(s == 0 for s in shifts),
                    },
                )
            )
        t = d.transitions[d.transitions["model_key"] == model]
        if len(t):
            counts = t["label"].value_counts().to_dict()
            detail = {
                **extra,
                **{k: int(counts.get(k, 0)) for k in ("consistent", "violating", "unconstrained")},
            }
            for label in ("consistent", "violating", "unconstrained"):
                out.append(
                    _proportion(
                        f"t3_{label}_rate",
                        "model",
                        int(counts.get(label, 0)),
                        len(t),
                        d.ci,
                        model=model,
                        detail=detail,
                    )
                )
    return out


# ---- between models (primary panel) ------------------------------------------------------------------
def panel_metrics(d: EvalData) -> list[Metric]:
    """Between-model agreement per condition with percentile bootstrap intervals over companies, and
    the within-model repeatability on the same scale (mean kappa over models) used by H6."""
    out: list[Metric] = []
    if len(d.primary) < 2:
        return out
    n_units = len(d.companies)
    for cond in d.conditions:
        r = d.ratings(cond)
        stats = {
            "t2_between_alpha_nominal": lambda idx, r=r: alpha_between(r, "t2", idx),
            "t2_between_fleiss_kappa": lambda idx, r=r: fleiss_between(r, idx),
            "t3_between_alpha_ordinal": lambda idx, r=r: alpha_between(r, "t3", idx),
            "t2_between_kappa_pairwise": lambda idx, r=r: kappa_between(r, "t2", idx),
            "t3_between_wkappa_pairwise": lambda idx, r=r: kappa_between(r, "t3", idx),
            "t2_within_kappa_mean": lambda idx, r=r: kappa_within(r, "t2", idx),
            "t3_within_wkappa_mean": lambda idx, r=r: kappa_within(r, "t3", idx),
        }
        for name, fn in stats.items():
            boot = bootstrap_ci(fn, n_units, resamples=d.resamples, seed=d.seed, confidence=d.ci)
            detail = {
                "models": d.primary,
                "resamples": boot.resamples,
                "n_valid_resamples": boot.n_valid,
            }
            if name.endswith(("alpha_nominal", "alpha_ordinal")):
                which = "t2" if name.startswith("t2") else "t3"
                level = "nominal" if which == "t2" else "ordinal"
                detail["per_repetition"] = {
                    str(rep): krippendorff_alpha(r.matrix(which, rep), level) for rep in r.reps
                }
            out.append(
                Metric(
                    name,
                    "condition",
                    value=boot.estimate,
                    condition=cond,
                    ci_low=boot.low,
                    ci_high=boot.high,
                    n=n_units,
                    detail=detail,
                )
            )
    return out


# ---- attribute agreement (MSA) -----------------------------------------------------------------------
def _msa_row(name: str, a: Agreement, scope: str, *, model=None, condition=None) -> Metric:
    return Metric(
        name,
        scope,
        value=a.rate if a.n else None,
        model=model,
        condition=condition,
        ci_low=a.low,
        ci_high=a.high,
        n=a.n,
        detail={"k": a.k},
    )


def msa_metrics(d: EvalData) -> list[Metric]:
    out: list[Metric] = []
    standard = {c: r.t2_class for c, r in d.standards.t2.items()}
    for cond in d.conditions:
        if len(d.primary) >= 1:
            res = attribute_agreement(d.ok, standard, cond, d.primary, d.reps)
            for m in d.primary:
                out.append(
                    _msa_row(
                        "msa_within_appraiser",
                        res.within[m],
                        "model_condition",
                        model=m,
                        condition=cond,
                    )
                )
                out.append(
                    _msa_row(
                        "msa_vs_standard",
                        res.vs_standard[m],
                        "model_condition",
                        model=m,
                        condition=cond,
                    )
                )
                out.append(
                    Metric(
                        "msa_kappa_vs_standard",
                        "model_condition",
                        value=res.kappa_vs_standard[m],
                        model=m,
                        condition=cond,
                        n=res.vs_standard[m].n * len(d.reps),
                    )
                )
            out.append(_msa_row("msa_between_appraisers", res.between, "condition", condition=cond))
            out.append(
                _msa_row("msa_all_vs_standard", res.all_vs_standard, "condition", condition=cond)
            )
        for m in sorted(set(d.roles) - set(d.primary)):
            res = attribute_agreement(d.ok, standard, cond, [m], d.reps)
            out.append(
                _msa_row(
                    "msa_within_appraiser",
                    res.within[m],
                    "model_condition",
                    model=m,
                    condition=cond,
                )
            )
            out.append(
                _msa_row(
                    "msa_vs_standard",
                    res.vs_standard[m],
                    "model_condition",
                    model=m,
                    condition=cond,
                )
            )
            out.append(
                Metric(
                    "msa_kappa_vs_standard",
                    "model_condition",
                    value=res.kappa_vs_standard[m],
                    model=m,
                    condition=cond,
                    n=res.vs_standard[m].n * len(d.reps),
                )
            )
    return out


# ---- grounding and the automatic part of the error taxonomy ------------------------------------------
def grounding_metrics(d: EvalData) -> list[Metric]:
    out: list[Metric] = []
    if d.claims.empty:
        return out
    for model in sorted(d.roles):
        for cond in d.conditions:
            sub = d.ok[(d.ok["model_key"] == model) & (d.ok["condition"] == cond)]
            if sub.empty:
                continue
            cl = d.claims[(d.claims["model_key"] == model) & (d.claims["condition"] == cond)]
            numeric = cl[cl["claim_type"] == "numeric"]
            n = len(numeric)
            extra = {
                "role": d.roles[model],
                "claims": len(cl),
                "pending_annotation": int((cl["status"] == "pending_annotation").sum()),
            }
            for status in SCORED_CLAIM_STATUSES:
                out.append(
                    _proportion(
                        f"claims_{status}",
                        "model_condition",
                        int((numeric["status"] == status).sum()),
                        n,
                        d.ci,
                        model=model,
                        condition=cond,
                        detail=extra,
                    )
                )
            bad_ids = set(numeric[numeric["status"].isin(["unsupported", "wrong"])]["judgment_id"])
            correct = set(sub[sub["correct"]]["judgment_id"])
            out.append(
                _proportion(
                    "taxonomy_objective_error",
                    "model_condition",
                    int((~sub["correct"]).sum()),
                    len(sub),
                    d.ci,
                    model=model,
                    condition=cond,
                    detail=extra,
                )
            )
            out.append(
                _proportion(
                    "taxonomy_unsupported_claim",
                    "model_condition",
                    len(bad_ids & correct),
                    len(sub),
                    d.ci,
                    model=model,
                    condition=cond,
                    detail={
                        **extra,
                        "note": "T2 correct but at least one unsupported or wrong numeric claim",
                    },
                )
            )
    return out


# ---- the controlled baseline next to the primary panel ----------------------------------------------
COMPARED = (
    "valid_share",
    "t2_accuracy",
    "t3_mean_rating",
    "t2_repeatability_agreement",
    "t3_repeatability_wkappa",
    "t2_context_distortion",
    "t3_consistent_rate",
    "t3_violating_rate",
    "claims_supported",
)


def baseline_comparison(metrics: list[Metric], roles: dict[str, str]) -> list[Metric]:
    """Descriptive differences baseline minus panel mean, per metric and condition. No tests (n = 1)."""
    out: list[Metric] = []
    primary = {m for m, r in roles.items() if r == "primary"}
    baseline = sorted(m for m, r in roles.items() if r == "baseline")
    for name in COMPARED:
        rows = [m for m in metrics if m.metric == name and m.value is not None]
        for cond in sorted({m.condition for m in rows}, key=lambda x: (x is None, x)):
            panel = [m.value for m in rows if m.model in primary and m.condition == cond]
            if not panel:
                continue
            for base in baseline:
                mine = next((m for m in rows if m.model == base and m.condition == cond), None)
                if mine is None:
                    continue
                out.append(
                    Metric(
                        "cmp_" + name,
                        "baseline",
                        value=mine.value - float(np.mean(panel)),
                        model=base,
                        condition=cond,
                        n=mine.n,
                        detail={
                            "baseline": mine.value,
                            "panel_mean": float(np.mean(panel)),
                            "panel_min": min(panel),
                            "panel_max": max(panel),
                            "panel_models": len(panel),
                            "metric": name,
                        },
                    )
                )
    return out


def compute_metrics(d: EvalData) -> list[Metric]:
    metrics = [
        *model_condition_metrics(d),
        *model_metrics(d),
        *panel_metrics(d),
        *msa_metrics(d),
        *grounding_metrics(d),
    ]
    metrics += baseline_comparison(metrics, d.roles)
    return metrics
