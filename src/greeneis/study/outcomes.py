"""What a degraded record does to a unit's footprint.

For each unit and each data-quality *profile* (which items are Measured, Estimated or Default) the unit's
inputs are rebuilt from the proxies, the footprint is recomputed, and the result is compared with the
footprint from the reference quantities. Emissions are linear in quantity, so coefficients (tCO2e per kg
or per kWh) come from the engine once and are reused; the tests check them against the engine.

Profiles are simulated assumptions about what a small unit keeps records of, not observed behaviour:

- ``bills_only``: electricity Measured (the bill); every fuel Estimated (spend / typical price)
- ``minimal``: everything Default (sector-typical intensity x scale)
- ``invoices_main``: electricity and the unit's largest fuel Measured; other fuels Estimated
- ``random_mix``: each item Measured / Estimated / Default with probability 0.4 / 0.4 / 0.2, seeded
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from decimal import Decimal

import numpy as np
import pandas as pd
from scipy.stats import kendalltau

from ..engine import Activity, calculate_activity
from ..factors import ELECTRICITY_ITEM, FactorLibrary, default_library
from ..trust import TrustConfig
from .cases import canonical_unit

PROFILES = ("bills_only", "minimal", "invoices_main", "random_mix")
H5_PROFILES = ("bills_only", "minimal")
CLASS_ORDER = ("measured", "estimated", "default")
THIN_LEAD = 0.10  # a lead of under 10 percentage points between the top two activities is "thin"


def coefficients(library: FactorLibrary | None = None) -> dict[str, float]:
    """tCO2e per canonical unit (kg of fuel, kWh of electricity) for every item, from the engine."""
    library = library or default_library()
    out = {}
    for item in [ELECTRICITY_ITEM, *(f.id for f in library.fuels)]:
        act = Activity(item_id=item, quantity=Decimal(1), unit=canonical_unit(item))
        out[item] = float(calculate_activity(act, library).co2e_t)
    return out


def assign_classes(
    profile: str, items: np.ndarray, e_ref: np.ndarray, rng: np.random.Generator
) -> np.ndarray:
    n = len(items)
    is_elec = items == ELECTRICITY_ITEM
    classes = np.full(n, "estimated", dtype=object)
    if profile == "bills_only":
        classes[is_elec] = "measured"
    elif profile == "minimal":
        classes[:] = "default"
    elif profile == "invoices_main":
        classes[is_elec] = "measured"
        fuels = np.where(~is_elec)[0]
        if len(fuels):
            classes[fuels[np.argmax(e_ref[fuels])]] = "measured"
    elif profile == "random_mix":
        classes = rng.choice(np.array(CLASS_ORDER, dtype=object), size=n, p=[0.4, 0.4, 0.2])
    else:
        raise ValueError(f"unknown profile {profile!r}")
    return classes


@dataclass(frozen=True)
class StudyData:
    items: pd.DataFrame  # one row per unit and item, with the proxy errors
    profiles: pd.DataFrame  # one row per unit and profile
    h5: pd.DataFrame  # one row per unit and base profile: error reduction by upgrade rule
    excluded: dict[str, int]  # "profile: reason" -> units left out
    coefficients: dict[str, float]


def _scores(cfg: TrustConfig) -> tuple[dict[str, float], dict[str, float]]:
    return (
        {c: float(v) for c, v in cfg.scores.items()},
        {c: float(v) for c, v in cfg.uncertainty.items()},
    )


def _trust_numbers(
    e: np.ndarray, classes: np.ndarray, s: dict[str, float], u: dict[str, float]
) -> tuple[float, float]:
    total = e.sum()
    score = np.array([s[c] for c in classes])
    unc = np.array([u[c] for c in classes])
    return float((e * score).sum() / total), float(np.sqrt(((e * unc) ** 2).sum()) / total)


def evaluate(
    cases: pd.DataFrame,
    cfg: TrustConfig | None = None,
    library: FactorLibrary | None = None,
    seed: int = 0,
    profiles: tuple[str, ...] = PROFILES,
    h5_profiles: tuple[str, ...] = H5_PROFILES,
) -> StudyData:
    """`cases` must already carry the proxy columns (see proxies.add_proxies)."""
    cfg = cfg or TrustConfig()
    k = coefficients(library)
    s, u = _scores(cfg)
    rows: list[dict] = []
    h5_rows: list[dict] = []
    excluded: dict[str, int] = {}

    for unit_id, g in cases.groupby("unit_id", sort=True):
        items = g["item_id"].to_numpy()
        q = g["quantity"].to_numpy(float)
        q_e = g["q_estimated"].to_numpy(float)
        q_d = g["q_default"].to_numpy(float)
        coef = np.array([k[i] for i in items])
        e_ref = q * coef
        total_ref = e_ref.sum()
        cluster = g["cluster"].iloc[0]
        crc = zlib.crc32(str(unit_id).encode())

        for p_index, profile in enumerate(profiles):
            rng = np.random.default_rng([seed, crc, p_index])
            classes = assign_classes(profile, items, e_ref, rng)
            q_deg = np.where(classes == "measured", q, np.where(classes == "estimated", q_e, q_d))
            if np.isnan(q_deg).any():
                key = f"{profile}: a needed proxy could not be formed"
                excluded[key] = excluded.get(key, 0) + 1
                continue
            e_deg = q_deg * coef
            total_deg = e_deg.sum()
            index, unc = _trust_numbers(e_deg, classes, s, u)
            n = len(items)
            top_ref = int(np.argmax(e_ref))
            row = {
                "unit_id": unit_id,
                "cluster": cluster,
                "profile": profile,
                "n_items": n,
                "n_measured": int((classes == "measured").sum()),
                "n_estimated": int((classes == "estimated").sum()),
                "n_default": int((classes == "default").sum()),
                "total_ref": total_ref,
                "total_deg": total_deg,
                "rel_error": (total_deg - total_ref) / total_ref,
                "abs_error": abs(total_deg - total_ref) / total_ref,
                "trust_index": index,
                "uncertainty": unc,
                "covered": bool(abs(total_ref - total_deg) <= unc * total_deg),
                "default_share_deg": float(e_deg[classes == "default"].sum() / total_deg),
                "top1_match": np.nan,
                "tau": np.nan,
                "lead_gap_ref": np.nan,
                "top_class": classes[top_ref],
            }
            if n >= 2:
                row["top1_match"] = float(int(np.argmax(e_deg)) == top_ref)
                ordered = np.sort(e_ref / total_ref)[::-1]
                row["lead_gap_ref"] = float(ordered[0] - ordered[1])
                if np.ptp(e_ref) > 0 and np.ptp(e_deg) > 0:
                    row["tau"] = float(kendalltau(e_ref, e_deg).statistic)
            rows.append(row)

            if profile in h5_profiles:
                cand = np.where(classes != "measured")[0]
                if len(cand) >= 2:
                    base = abs(total_deg - total_ref) / total_ref
                    after = np.abs(total_deg - e_deg[cand] + e_ref[cand] - total_ref) / total_ref
                    gain = base - after  # positive: the error shrank
                    largest = int(np.argmax(e_deg[cand]))
                    scores = np.array([s[c] for c in classes[cand]])
                    lowest = np.flatnonzero(scores == scores.min())
                    pick = int(rng.choice(lowest))  # ties broken at random
                    h5_rows.append(
                        {
                            "unit_id": unit_id,
                            "cluster": cluster,
                            "profile": profile,
                            "n_candidates": len(cand),
                            "base_abs_error": base,
                            "r_largest": float(gain[largest]),
                            "r_lowest": float(gain[pick]),
                            "r_random": float(gain.mean()),
                        }
                    )

    items_df = cases.loc[
        :, ["unit_id", "item_id", "cluster", "eps_estimated", "eps_default"]
    ].copy()
    return StudyData(
        items=items_df,
        profiles=pd.DataFrame(rows),
        h5=pd.DataFrame(h5_rows),
        excluded=excluded,
        coefficients=k,
    )
