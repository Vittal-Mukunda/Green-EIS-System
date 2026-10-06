"""Position effect (spec §5): companies are batched in one prompt, so does a company's position in
the prompt relate to T2 correctness or to the T3 rating?

Descriptive, as the spec asks: a logistic model of T2 correctness and an ordered-logit model of the T3
rating, each with the (centred) position as the covariate and model and condition as fixed effects, fitted on
the primary panel; the controlled baseline gets its own fit. Standard errors treat judgments as
independent, although the same company appears several times (a pilot-scale simplification), so the
intervals are indicative. A model that cannot be estimated (no variation, perfect separation, no
convergence) is reported as such, never silently dropped.
"""

from __future__ import annotations

import math
import warnings

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from statsmodels.miscmodels.ordinal_model import OrderedModel

from gauge.evaluate.metrics import EvalData
from gauge.evaluate.results import Metric
from gauge.stats.primitives import clopper_pearson

ESTIMATION_ERRORS = (np.linalg.LinAlgError, ValueError, ArithmeticError, KeyError)


def _frame(ok: pd.DataFrame) -> pd.DataFrame:
    out = ok.copy()
    out["pos_c"] = out["position"].astype(float) - out["position"].astype(float).mean()
    out["correct_i"] = out["correct"].astype(int)
    out["rating"] = out["t3_rating"].astype(int)
    return out


def _not_estimable(name: str, scope: str, reason: str, n: int, **keys) -> Metric:
    return Metric(
        name, scope, value=None, n=n, detail={"estimable": False, "reason": reason}, **keys
    )


def _logit(data: pd.DataFrame, scope: str, **keys) -> Metric:
    name, n = "position_t2_logit", len(data)
    if n < 10 or data["correct_i"].nunique() < 2 or data["pos_c"].nunique() < 2:
        return _not_estimable(
            name, scope, "T2 correctness has no variation or too few judgments", n, **keys
        )
    terms = ["pos_c"]
    if data["model_key"].nunique() > 1:
        terms.append("C(model_key)")
    if data["condition"].nunique() > 1:
        terms.append("C(condition)")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit = smf.logit("correct_i ~ " + " + ".join(terms), data).fit(disp=False, maxiter=200)
        coef, se = float(fit.params["pos_c"]), float(fit.bse["pos_c"])
        low, high = (float(x) for x in fit.conf_int().loc["pos_c"])
        converged = bool(fit.mle_retvals.get("converged", True))
        p = float(fit.pvalues["pos_c"])
    except ESTIMATION_ERRORS as exc:
        return _not_estimable(name, scope, f"{type(exc).__name__}: {exc}", n, **keys)
    if not all(math.isfinite(x) for x in (coef, se, low, high)) or se > 50:
        return _not_estimable(name, scope, "perfect or near-perfect separation", n, **keys)
    return Metric(
        name,
        scope,
        value=math.exp(coef),
        ci_low=math.exp(low),
        ci_high=math.exp(high),
        n=n,
        **keys,
        detail={
            "estimable": True,
            "coef": coef,
            "se": se,
            "p": p,
            "converged": converged,
            "odds_ratio_per_10_positions": math.exp(10 * coef),
            "terms": terms,
            "note": "odds ratio of a correct T2 class per one position later in the prompt",
        },
    )


def _ordinal(data: pd.DataFrame, scope: str, **keys) -> Metric:
    name, n = "position_t3_ordinal", len(data)
    if n < 10 or data["rating"].nunique() < 2 or data["pos_c"].nunique() < 2:
        return _not_estimable(
            name, scope, "T3 ratings have no variation or too few judgments", n, **keys
        )
    exog = data[["pos_c"]].copy()
    for column in ("model_key", "condition"):
        if data[column].nunique() > 1:
            dummies = pd.get_dummies(data[column], prefix=column, drop_first=True, dtype=float)
            exog = pd.concat([exog, dummies], axis=1)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = OrderedModel(data["rating"].to_numpy(), exog.to_numpy(), distr="logit")
            fit = model.fit(method="bfgs", disp=False, maxiter=500)
        coef, se = float(fit.params[0]), float(fit.bse[0])
        low, high = (float(x) for x in fit.conf_int()[0])
        p = float(fit.pvalues[0])
        converged = bool(fit.mle_retvals.get("converged", True))
    except ESTIMATION_ERRORS as exc:
        return _not_estimable(name, scope, f"{type(exc).__name__}: {exc}", n, **keys)
    if not all(math.isfinite(x) for x in (coef, se, low, high)) or se > 50:
        return _not_estimable(name, scope, "perfect or near-perfect separation", n, **keys)
    return Metric(
        name,
        scope,
        value=math.exp(coef),
        ci_low=math.exp(low),
        ci_high=math.exp(high),
        n=n,
        **keys,
        detail={
            "estimable": True,
            "coef": coef,
            "se": se,
            "p": p,
            "converged": converged,
            "note": "odds ratio of a higher T3 rating per one position later in the prompt",
        },
    )


def _terciles(data: pd.DataFrame, n_companies: int, scope: str, **keys) -> list[Metric]:
    out = []
    tercile = np.ceil(3 * data["position"].astype(float) / n_companies).clip(1, 3).astype(int)
    for t in (1, 2, 3):
        sub = data[tercile == t]
        if sub.empty:
            continue
        k, n = int(sub["correct"].sum()), len(sub)
        low, high = clopper_pearson(k, n)
        out.append(
            Metric(
                "position_t2_accuracy_tercile",
                scope,
                value=k / n,
                ci_low=low,
                ci_high=high,
                n=n,
                detail={
                    "tercile": t,
                    "positions": [int(sub["position"].min()), int(sub["position"].max())],
                },
                **keys,
            )
        )
        out.append(
            Metric(
                "position_t3_mean_tercile",
                scope,
                value=float(sub["rating"].mean()),
                n=n,
                detail={"tercile": t},
                **keys,
            )
        )
    return out


def position_effects(d: EvalData) -> list[Metric]:
    out: list[Metric] = []
    primary = d.ok[d.ok["model_key"].isin(d.primary)]
    if not primary.empty:
        data = _frame(primary)
        out += [_logit(data, "panel"), _ordinal(data, "panel")]
        out += _terciles(data, len(d.companies), "panel")
    for model in sorted(m for m, r in d.roles.items() if r != "primary"):
        sub = d.ok[d.ok["model_key"] == model]
        if sub.empty:
            continue
        data = _frame(sub)
        out += [_logit(data, "baseline", model=model), _ordinal(data, "baseline", model=model)]
        out += _terciles(data, len(d.companies), "baseline", model=model)
    return out
