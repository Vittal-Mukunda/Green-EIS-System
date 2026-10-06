"""Rating matrices and the agreement statistics computed on them (spec §5), written so that every
statistic is a function of an array of company indices: the bootstrap resamples companies by passing
index arrays with repeats.

Between-model agreement uses one rating per model and company, so it is computed per repetition and
averaged over repetitions. Within-model repeatability compares repetition 1 with repetition 2. For the
hypotheses that compare the two (H6) both are expressed as Cohen's kappa over pairs of rating
vectors, so they are on the same scale.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np
import pandas as pd

from gauge.stats.primitives import (
    NAN,
    disagreement_matrix,
    fleiss_kappa,
    kappa_from_codes,
    krippendorff_alpha,
)
from gauge.vocab import T2_CLASSES

T2_CODE = {c: i for i, c in enumerate(T2_CLASSES)}
N_RATINGS = 5
KAPPA_T2 = disagreement_matrix(len(T2_CLASSES), None)
KAPPA_T3 = disagreement_matrix(N_RATINGS, "quadratic")


@dataclass(frozen=True)
class Ratings:
    """Models x companies matrices (NaN = no valid judgment) per repetition, for one condition."""

    condition: str
    models: list[str]
    companies: list[str]
    reps: list[int]
    t2: dict[int, np.ndarray]  # class code 0..2
    t3: dict[int, np.ndarray]  # rating 1..5

    def matrix(self, which: str, rep: int) -> np.ndarray:
        return (self.t2 if which == "t2" else self.t3)[rep]


def build_ratings(
    ok: pd.DataFrame, models: list[str], condition: str, reps: list[int], companies: list[str]
) -> Ratings:
    t2 = {r: np.full((len(models), len(companies)), np.nan) for r in reps}
    t3 = {r: np.full((len(models), len(companies)), np.nan) for r in reps}
    m_index = {m: i for i, m in enumerate(models)}
    c_index = {c: i for i, c in enumerate(companies)}
    sub = ok[ok["condition"] == condition]
    for model, rep, code, cls, rating in zip(
        sub["model_key"],
        sub["repetition"],
        sub["company_code"],
        sub["t2_class"],
        sub["t3_rating"],
        strict=True,
    ):
        if model in m_index and rep in t2 and code in c_index:
            t2[rep][m_index[model], c_index[code]] = T2_CODE[cls]
            t3[rep][m_index[model], c_index[code]] = rating
    return Ratings(condition, list(models), list(companies), list(reps), t2, t3)


def _nanmean(values: list[float]) -> float:
    finite = [v for v in values if np.isfinite(v)]
    return float(np.mean(finite)) if finite else NAN


# ---- between models ------------------------------------------------------------------------------
def alpha_between(r: Ratings, which: str, idx: np.ndarray) -> float:
    """Krippendorff's alpha across models (nominal for T2, ordinal for T3), mean over repetitions."""
    level = "nominal" if which == "t2" else "ordinal"
    return _nanmean([krippendorff_alpha(r.matrix(which, rep)[:, idx], level) for rep in r.reps])


def fleiss_between(r: Ratings, idx: np.ndarray) -> float:
    """Fleiss' kappa for T2 across models (companies rated by every model), mean over repetitions."""
    values = []
    k = len(T2_CLASSES)
    for rep in r.reps:
        cols = r.matrix("t2", rep)[:, idx]
        complete = cols[:, ~np.isnan(cols).any(axis=0)].astype(int)
        if complete.shape[1] < 2 or complete.shape[0] < 2:
            continue
        table = np.zeros((complete.shape[1], k))
        for i in range(k):
            table[:, i] = (complete == i).sum(axis=0)
        values.append(fleiss_kappa(table))
    return _nanmean(values)


def kappa_between(r: Ratings, which: str, idx: np.ndarray) -> float:
    """Mean Cohen's kappa over all pairs of models and all repetitions."""
    weights = KAPPA_T2 if which == "t2" else KAPPA_T3
    values = []
    for rep in r.reps:
        m = r.matrix(which, rep)[:, idx]
        for i, j in combinations(range(len(r.models)), 2):
            values.append(_pair_kappa(m[i], m[j], which, weights))
    return _nanmean(values)


# ---- within a model -------------------------------------------------------------------------------
def _pair_kappa(a: np.ndarray, b: np.ndarray, which: str, weights: np.ndarray) -> float:
    both = ~np.isnan(a) & ~np.isnan(b)
    if both.sum() < 2:
        return NAN
    shift = 0 if which == "t2" else 1  # ratings 1..5 -> codes 0..4
    return kappa_from_codes(
        a[both].astype(np.intp) - shift, b[both].astype(np.intp) - shift, weights
    )


def kappa_within(r: Ratings, which: str, idx: np.ndarray, model: str | None = None) -> float:
    """Cohen's kappa between repetition 1 and 2 of a model (or the mean over models)."""
    if len(r.reps) < 2:
        return NAN
    weights = KAPPA_T2 if which == "t2" else KAPPA_T3
    first, second = r.reps[:2]
    a, b = r.matrix(which, first)[:, idx], r.matrix(which, second)[:, idx]
    rows = range(len(r.models)) if model is None else [r.models.index(model)]
    return _nanmean([_pair_kappa(a[i], b[i], which, weights) for i in rows])
