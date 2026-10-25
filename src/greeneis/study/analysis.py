"""The pre-specified analysis of H1-H5 (docs/RESEARCH_DESIGN.md section 4).

Every hypothesis is stated as a **falsification condition**. A cluster bootstrap resamples clusters (units
that share prices are not independent) and counts the replicates in which the condition holds; that share
is the hypothesis's p-value, (k + 1) / (B + 1). The five p-values are adjusted with Holm's method. A
hypothesis is "supported" when its adjusted p is below 0.05, "not supported" otherwise, and "insufficient
data" when there are too few clusters or rows to say anything.

| H  | falsified in a replicate when ...                                                                 |
|----|----------------------------------------------------------------------------------------------------|
| H1 | the median of (|error of Default| - |error of Estimated|) is not positive                           |
| H2 | q90 of |error| is within [u/1.5, 1.5u] for both classes AND pooled interval coverage is in [80%, 95%] |
| H3 | Spearman correlation of trust index with |total error| is not negative, pooled or within random_mix |
| H4 | P(top hotspot kept), bills_only profile, is below 80%, OR thick-lead units do not keep it more often |
| H5 | upgrading the largest hotspot's input first does not beat both lowest-trust-first and random        |

Thresholds are placeholders to confirm. Nothing here is tuned after seeing results.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from ..trust import PLACEHOLDER_UNCERTAINTY
from .outcomes import THIN_LEAD, StudyData

MIN_CLUSTERS = 10
MIN_ROWS = 30
COVERAGE_BAND = (0.80, 0.95)
CALIBRATION_FACTOR = 1.5
TOP1_FLOOR = 0.80
ALPHA = 0.05


class ClusterSampler:
    """Draws bootstrap samples of a table by resampling whole clusters."""

    def __init__(self, df: pd.DataFrame, columns: list[str], cluster: str = "cluster"):
        ordered = df.sort_values(cluster, kind="stable")
        self.arrays = {c: ordered[c].to_numpy() for c in columns}
        keys = ordered[cluster].to_numpy()
        _, starts = np.unique(keys, return_index=True)
        ends = np.append(starts[1:], len(keys))
        self.slices = list(zip(starts.tolist(), ends.tolist(), strict=True))
        self.n_clusters = len(self.slices)
        self.n_rows = len(ordered)

    def whole(self) -> dict[str, np.ndarray]:
        return self.arrays

    def draw(self, picks: np.ndarray) -> dict[str, np.ndarray]:
        parts = [self.slices[i] for i in picks]
        return {
            c: np.concatenate([a[s:e] for s, e in parts]) if parts else a[:0]
            for c, a in self.arrays.items()
        }


def _p(falsified: int, replicates: int) -> float:
    return (falsified + 1) / (replicates + 1)


def holm(p_values: dict[str, float]) -> dict[str, float]:
    """Holm-adjusted p-values (step-down), keyed like the input."""
    order = sorted(p_values, key=lambda k: p_values[k])
    m = len(order)
    adjusted: dict[str, float] = {}
    running = 0.0
    for i, key in enumerate(order):
        running = max(running, min(1.0, (m - i) * p_values[key]))
        adjusted[key] = running
    return adjusted


@dataclass
class Test:
    name: str
    statement: str
    estimate: dict
    falsified_p: float | None
    n_clusters: int
    n_rows: int
    note: str = ""
    adjusted_p: float | None = None
    verdict: str = "insufficient data"


def _ci(values: list[float]) -> tuple[float, float]:
    arr = np.array([v for v in values if not np.isnan(v)])
    if arr.size == 0:
        return (float("nan"), float("nan"))
    return float(np.percentile(arr, 2.5)), float(np.percentile(arr, 97.5))


def _run(
    sampler: ClusterSampler,
    statistic: Callable[[dict[str, np.ndarray]], float],
    falsified: Callable[[dict[str, np.ndarray]], bool],
    n_boot: int,
    rng: np.random.Generator,
) -> tuple[float, tuple[float, float], float | None]:
    """Point estimate, percentile CI of the statistic, and the bootstrap falsification p-value."""
    point = statistic(sampler.whole())
    stats, bad = [], 0
    for _ in range(n_boot):
        sample = sampler.draw(rng.integers(0, sampler.n_clusters, sampler.n_clusters))
        stats.append(statistic(sample))
        bad += bool(falsified(sample))
    return point, _ci(stats), _p(bad, n_boot)


def _usable(n_clusters: int, n_rows: int) -> bool:
    return n_clusters >= MIN_CLUSTERS and n_rows >= MIN_ROWS


def analyse(
    data: StudyData,
    n_boot: int = 1000,
    seed: int = 0,
    placeholder_u: dict | None = None,
) -> dict:
    rng = np.random.default_rng(seed)
    pu = {k: float(v) for k, v in (placeholder_u or PLACEHOLDER_UNCERTAINTY).items()}
    tests: dict[str, Test] = {}

    # ---- H1: Default errors exceed Estimated errors -------------------------------------------
    it = data.items.dropna(subset=["eps_estimated", "eps_default"]).copy()
    it["diff"] = it["eps_default"].abs() - it["eps_estimated"].abs()
    s1 = ClusterSampler(it, ["diff"]) if len(it) else None
    if s1 and _usable(s1.n_clusters, s1.n_rows):
        point, ci, p = _run(
            s1,
            lambda d: float(np.median(d["diff"])),
            lambda d: np.median(d["diff"]) <= 0,
            n_boot,
            rng,
        )
        tests["H1"] = Test(
            "H1",
            "Default inputs have larger realised error than Estimated inputs",
            {
                "median_difference": point,
                "ci95": ci,
                "median_abs_error_estimated": float(it["eps_estimated"].abs().median()),
                "median_abs_error_default": float(it["eps_default"].abs().median()),
            },
            p,
            s1.n_clusters,
            s1.n_rows,
        )
    else:
        tests["H1"] = Test(
            "H1",
            "Default inputs have larger realised error than Estimated inputs",
            {},
            None,
            s1.n_clusters if s1 else 0,
            len(it),
        )

    # ---- H2: placeholder ranges are miscalibrated --------------------------------------------
    pr = data.profiles
    if len(it) and len(pr):
        i2 = it.assign(ae=it["eps_estimated"].abs(), ad=it["eps_default"].abs())[
            ["ae", "ad", "cluster"]
        ]
        p2 = pr[["covered", "cluster"]].assign(covered=pr["covered"].astype(float))
        # both tables are resampled over the same cluster labels, so one draw serves both
        labels = sorted(set(i2["cluster"]) & set(p2["cluster"]))
        s2a = ClusterSampler(i2[i2["cluster"].isin(labels)], ["ae", "ad"])
        s2b = ClusterSampler(p2[p2["cluster"].isin(labels)], ["covered"])
        n2 = s2a.n_clusters

        def h2_stats(a: dict, b: dict) -> tuple[float, float, float]:
            return (
                float(np.quantile(a["ae"], 0.9)),
                float(np.quantile(a["ad"], 0.9)),
                float(b["covered"].mean()),
            )

        def h2_holds(q_e: float, q_d: float, cov: float) -> bool:
            lo_e, hi_e = pu["estimated"] / CALIBRATION_FACTOR, pu["estimated"] * CALIBRATION_FACTOR
            lo_d, hi_d = pu["default"] / CALIBRATION_FACTOR, pu["default"] * CALIBRATION_FACTOR
            return (
                lo_e <= q_e <= hi_e
                and lo_d <= q_d <= hi_d
                and COVERAGE_BAND[0] <= cov <= COVERAGE_BAND[1]
            )

        if _usable(n2, s2a.n_rows):
            point = h2_stats(s2a.whole(), s2b.whole())
            reps, ok = [], 0
            for _ in range(n_boot):
                picks = rng.integers(0, n2, n2)
                # the two samplers share the sorted label order, so one draw serves both
                stat = h2_stats(s2a.draw(picks), s2b.draw(picks))
                reps.append(stat)
                ok += h2_holds(*stat)
            by_profile = pr.groupby("profile")["covered"].mean().to_dict()
            tests["H2"] = Test(
                "H2",
                "The placeholder uncertainty ranges are miscalibrated",
                {
                    "q90_abs_error_estimated": point[0],
                    "q90_abs_error_default": point[1],
                    "placeholder_u": {"estimated": pu["estimated"], "default": pu["default"]},
                    "pooled_coverage": point[2],
                    "coverage_by_profile": by_profile,
                    "ci95_q90_estimated": _ci([r[0] for r in reps]),
                    "ci95_q90_default": _ci([r[1] for r in reps]),
                    "ci95_coverage": _ci([r[2] for r in reps]),
                },
                _p(ok, n_boot),
                n2,
                s2a.n_rows,
                note="The nominal interval is read as a 90% interval (design decision pending).",
            )
    if "H2" not in tests:
        tests["H2"] = Test(
            "H2", "The placeholder uncertainty ranges are miscalibrated", {}, None, 0, 0
        )

    # ---- H3: trust index tracks realised error -----------------------------------------------
    # Pooled across profiles the correlation is partly built in (profiles differ in class mix by
    # design), so the hypothesis also needs it to hold WITHIN random_mix, where the mix varies by unit.
    p3 = pr.dropna(subset=["trust_index", "abs_error"]) if len(pr) else pr
    s3 = (
        ClusterSampler(p3, ["trust_index", "abs_error", "default_share_deg", "profile"])
        if len(p3)
        else None
    )
    if s3 and _usable(s3.n_clusters, s3.n_rows):

        def _rho(t: np.ndarray, e: np.ndarray) -> float:
            if len(t) < 3 or np.ptp(t) == 0 or np.ptp(e) == 0:
                return float("nan")
            return float(spearmanr(t, e).statistic)

        def rhos(d: dict) -> tuple[float, float]:
            within = d["profile"] == "random_mix"
            return (
                _rho(d["trust_index"], d["abs_error"]),
                _rho(d["trust_index"][within], d["abs_error"][within]),
            )

        def falsified3(d: dict) -> bool:
            pooled, within = rhos(d)
            return not (pooled < 0 and within < 0)

        pooled, within = rhos(s3.whole())
        reps, bad = [], 0
        for _ in range(n_boot):
            d = s3.draw(rng.integers(0, s3.n_clusters, s3.n_clusters))
            reps.append(rhos(d))
            bad += falsified3(d)
        w = s3.whole()
        tests["H3"] = Test(
            "H3",
            "The trust index tracks realised total error",
            {
                "spearman_rho_pooled": pooled,
                "ci95_pooled": _ci([r[0] for r in reps]),
                "spearman_rho_within_random_mix": within,
                "ci95_within_random_mix": _ci([r[1] for r in reps]),
                "naive_default_share_rho": _rho(w["default_share_deg"], w["abs_error"]),
            },
            _p(bad, n_boot),
            s3.n_clusters,
            s3.n_rows,
            note="Both the pooled and the within-random_mix correlations must be negative. "
            "naive_default_share_rho (share of emissions from Default inputs vs error) is descriptive.",
        )
    else:
        tests["H3"] = Test(
            "H3",
            "The trust index tracks realised total error",
            {},
            None,
            s3.n_clusters if s3 else 0,
            len(p3),
        )

    # ---- H4: the top hotspot is robust, less so when the lead is thin -------------------------
    p4 = (
        pr[(pr["profile"] == "bills_only")].dropna(subset=["top1_match", "lead_gap_ref"])
        if len(pr)
        else pr
    )
    s4 = (
        ClusterSampler(
            p4.assign(thin=(p4["lead_gap_ref"] < THIN_LEAD).astype(float)), ["top1_match", "thin"]
        )
        if len(p4)
        else None
    )
    if s4 and _usable(s4.n_clusters, s4.n_rows):

        def rates(d: dict) -> tuple[float, float, float]:
            thin = d["thin"] == 1
            overall = float(d["top1_match"].mean())
            r_thin = float(d["top1_match"][thin].mean()) if thin.any() else float("nan")
            r_thick = float(d["top1_match"][~thin].mean()) if (~thin).any() else float("nan")
            return overall, r_thin, r_thick

        def falsified4(d: dict) -> bool:
            overall, r_thin, r_thick = rates(d)
            gap_ok = not np.isnan(r_thin) and not np.isnan(r_thick) and r_thick - r_thin > 0
            return overall < TOP1_FLOOR or not gap_ok

        overall, r_thin, r_thick = rates(s4.whole())
        reps = []
        bad = 0
        for _ in range(n_boot):
            d = s4.draw(rng.integers(0, s4.n_clusters, s4.n_clusters))
            reps.append(rates(d))
            bad += falsified4(d)
        tests["H4"] = Test(
            "H4",
            "The top hotspot is usually robust, but less so when the lead is thin",
            {
                "p_top1_kept": overall,
                "ci95": _ci([r[0] for r in reps]),
                "p_kept_thin_lead": r_thin,
                "p_kept_thick_lead": r_thick,
                "thin_lead_below": THIN_LEAD,
                "floor": TOP1_FLOOR,
            },
            _p(bad, n_boot),
            s4.n_clusters,
            s4.n_rows,
            note="Units with a single energy item are excluded (the top hotspot is trivially kept).",
        )
    else:
        tests["H4"] = Test(
            "H4",
            "The top hotspot is usually robust, but less so when the lead is thin",
            {},
            None,
            s4.n_clusters if s4 else 0,
            len(p4),
        )

    # ---- H5: largest-first beats lowest-trust-first and random --------------------------------
    h5 = data.h5[data.h5["profile"] == "bills_only"] if len(data.h5) else data.h5
    s5 = ClusterSampler(h5, ["r_largest", "r_lowest", "r_random"]) if len(h5) else None
    if s5 and _usable(s5.n_clusters, s5.n_rows):

        def margin(d: dict) -> float:
            return float(d["r_largest"].mean() - max(d["r_lowest"].mean(), d["r_random"].mean()))

        point, ci, p = _run(s5, margin, lambda d: not (margin(d) > 0), n_boot, rng)
        w = s5.whole()
        tests["H5"] = Test(
            "H5",
            "Upgrading the largest hotspot's input first cuts total error more than the alternatives",
            {
                "margin_over_best_alternative": point,
                "ci95": ci,
                "mean_error_reduction": {
                    "largest_first": float(w["r_largest"].mean()),
                    "lowest_trust_first": float(w["r_lowest"].mean()),
                    "random": float(w["r_random"].mean()),
                },
            },
            p,
            s5.n_clusters,
            s5.n_rows,
            note="Reduction in |relative total error| after upgrading one input to Measured; "
            "positive is better. Base profile bills_only.",
        )
    else:
        tests["H5"] = Test(
            "H5",
            "Upgrading the largest hotspot's input first cuts total error more "
            "than the alternatives",
            {},
            None,
            s5.n_clusters if s5 else 0,
            len(h5),
        )

    # ---- Holm over the hypotheses that could be tested; verdicts --------------------------------
    ps = {k: t.falsified_p for k, t in tests.items() if t.falsified_p is not None}
    adj = holm(ps) if ps else {}
    for k, t in tests.items():
        if t.falsified_p is None:
            t.verdict = "insufficient data"
            continue
        t.adjusted_p = adj[k]
        t.verdict = "supported" if adj[k] < ALPHA else "not supported"

    return {
        "tests": {k: t.__dict__ for k, t in tests.items()},
        "descriptives": descriptives(data),
        "settings": {
            "n_boot": n_boot,
            "seed": seed,
            "alpha": ALPHA,
            "min_clusters": MIN_CLUSTERS,
            "min_rows": MIN_ROWS,
            "coverage_band": COVERAGE_BAND,
            "calibration_factor": CALIBRATION_FACTOR,
            "top1_floor": TOP1_FLOOR,
        },
    }


def descriptives(data: StudyData) -> dict:
    out: dict = {"excluded": data.excluded}
    pr = data.profiles
    if len(pr):
        g = pr.groupby("profile")
        out["by_profile"] = {
            name: {
                "units": int(len(grp)),
                "mean_abs_total_error": float(grp["abs_error"].mean()),
                "median_abs_total_error": float(grp["abs_error"].median()),
                "mean_trust_index": float(grp["trust_index"].mean()),
                "coverage": float(grp["covered"].mean()),
                "top1_kept": float(grp["top1_match"].mean()),
                "mean_kendall_tau": float(grp["tau"].mean()),
            }
            for name, grp in g
        }
    it = data.items
    if len(it):
        out["item_errors"] = {
            c: {
                "n": int(it[c].notna().sum()),
                "median_abs": float(it[c].abs().median()),
                "q90_abs": float(it[c].abs().quantile(0.9)),
                "mean_signed": float(it[c].mean()),
            }
            for c in ("eps_estimated", "eps_default")
        }
    return out
