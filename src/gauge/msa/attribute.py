"""Attribute agreement analysis (measurement-system analysis for categorical results).

Appraisers are the models, trials the repetitions, parts the companies, and the standard is the T2
class from the frozen rule. As in the usual attribute-agreement report, four percentages are given,
each over the companies for which every needed rating exists (a company is dropped from a cell if
a required rating is missing or still invalid after the repair), with exact binomial 95% intervals:

  within appraiser     the appraiser's trials all agree with each other;
  appraiser vs standard   all of the appraiser's trials equal the standard;
  between appraisers   every trial of every appraiser agrees (all models, all repetitions);
  all vs standard      every trial of every appraiser equals the standard.

Cohen's kappa of each appraiser's trials against the standard is added for information. See
docs/METHODS.md for why this is used instead of continuous Gage R&R.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import pandas as pd

from gauge.stats.primitives import NAN, clopper_pearson, cohen_kappa
from gauge.vocab import T2_CLASSES


@dataclass(frozen=True)
class Agreement:
    k: int  # companies in agreement
    n: int  # companies with all the ratings this cell needs
    low: float
    high: float

    @property
    def rate(self) -> float:
        return self.k / self.n if self.n else NAN


def _agreement(k: int, n: int) -> Agreement:
    low, high = clopper_pearson(k, n) if n else (NAN, NAN)
    return Agreement(k, n, low, high)


@dataclass
class MsaResult:
    condition: str
    appraisers: list[str]
    trials: list[int]
    within: dict[str, Agreement] = field(default_factory=dict)
    vs_standard: dict[str, Agreement] = field(default_factory=dict)
    kappa_vs_standard: dict[str, float] = field(default_factory=dict)
    between: Agreement | None = None
    all_vs_standard: Agreement | None = None


def attribute_agreement(
    frame: pd.DataFrame,
    standard: Mapping[str, str],
    condition: str,
    appraisers: Sequence[str],
    trials: Sequence[int],
) -> MsaResult:
    """`frame` holds valid judgments (columns model_key, condition, repetition, company_code,
    t2_class); `standard` maps company code -> rule class."""
    result = MsaResult(condition, list(appraisers), list(trials))
    sub = frame[frame["condition"] == condition]
    ratings: dict[tuple[str, str], dict[int, str]] = {}
    for model, rep, code, cls in zip(
        sub["model_key"], sub["repetition"], sub["company_code"], sub["t2_class"], strict=True
    ):
        ratings.setdefault((model, code), {})[int(rep)] = cls
    companies = sorted(standard)

    def complete(model: str, code: str) -> list[str] | None:
        got = ratings.get((model, code), {})
        return [got[t] for t in trials] if all(t in got for t in trials) else None

    for model in appraisers:
        k_within = n_within = k_std = 0
        pooled_model, pooled_std = [], []
        for code in companies:
            trial_ratings = complete(model, code)
            if trial_ratings is None:
                continue
            n_within += 1
            k_within += len(set(trial_ratings)) == 1
            k_std += all(r == standard[code] for r in trial_ratings)
            pooled_model += trial_ratings
            pooled_std += [standard[code]] * len(trial_ratings)
        result.within[model] = _agreement(k_within, n_within)
        result.vs_standard[model] = _agreement(k_std, n_within)
        result.kappa_vs_standard[model] = (
            cohen_kappa(pooled_model, pooled_std, labels=list(T2_CLASSES)) if pooled_model else NAN
        )

    k_between = k_all = n_all = 0
    for code in companies:
        per_model = [complete(m, code) for m in appraisers]
        if any(r is None for r in per_model):
            continue
        flat = [r for rs in per_model for r in rs]
        n_all += 1
        k_between += len(set(flat)) == 1
        k_all += all(r == standard[code] for r in flat)
    result.between = _agreement(k_between, n_all)
    result.all_vs_standard = _agreement(k_all, n_all)
    return result
