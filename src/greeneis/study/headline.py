"""Plain readings of a study result file, for pages that explain it to people who did not run it.

Every figure here is read straight from the JSON written by `greeneis.study.run`; nothing is recomputed.
The one derived quantity is the order of the fuels. A reader who wants the full tables uses the Study
results page.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

FUEL_NAMES = {"grid_electricity": "Electricity", "coal": "Coal", "lpg": "LPG"}


@dataclass(frozen=True)
class FuelError:
    """How far a proxy was from the reported quantity for one fuel (absolute relative error)."""

    item: str
    name: str
    records: int
    estimated_median: float
    estimated_q90: float
    default_median: float
    default_q90: float


@dataclass(frozen=True)
class Headline:
    source: str
    reference_quantity: str
    synthetic: bool
    only_sector: str | None
    factories: int
    records: int
    states: int
    multi_item_factories: int | None
    estimated_median: float
    default_median: float
    estimated_q90: float
    default_q90: float
    placeholder_estimated: float
    placeholder_default: float
    coverage: float
    coverage_by_profile: dict[str, float]
    top1_kept: float
    top1_thin_lead: float | None
    top1_thick_lead: float | None
    thin_lead_below: float | None
    h5_reduction: dict[str, float]
    h5_rows: int
    verdicts: dict[str, str]
    rows_by_test: dict[str, int]
    spearman_pooled: float
    spearman_within_random_mix: float
    naive_default_share_rho: float
    factories_in_file: int | None
    fuels: tuple[FuelError, ...]
    placeholder_status: str


def _est(tests: dict, name: str) -> dict:
    return tests[name]["estimate"] or {}


def headline(result: dict) -> Headline:
    """The figures a visitor needs from a result dict. Raises KeyError if it is not a study result."""
    tests, prov, desc = result["tests"], result["provenance"], result["descriptives"]
    h1, h2, h3, h4, h5 = (_est(tests, f"H{i}") for i in range(1, 6))
    fuels = tuple(
        sorted(
            (
                FuelError(
                    item=item,
                    name=FUEL_NAMES.get(item, item),
                    records=int(d["eps_estimated"]["n"]),
                    estimated_median=float(d["eps_estimated"]["median_abs"]),
                    estimated_q90=float(d["eps_estimated"]["q90_abs"]),
                    default_median=float(d["eps_default"]["median_abs"]),
                    default_q90=float(d["eps_default"]["q90_abs"]),
                )
                for item, d in desc.get("item_errors_by_item", {}).items()
            ),
            key=lambda f: -f.records,
        )
    )
    return Headline(
        source=prov["source"],
        reference_quantity=prov["reference_quantity"],
        synthetic=bool(prov["synthetic"]),
        only_sector=prov.get("only_sector"),
        factories=int(prov["units"]),
        records=int(prov["rows"]),
        states=int(prov["clusters"]),
        multi_item_factories=prov.get("data_log", {}).get("factories with two or more items"),
        estimated_median=float(h1["median_abs_error_estimated"]),
        default_median=float(h1["median_abs_error_default"]),
        estimated_q90=float(h2["q90_abs_error_estimated"]),
        default_q90=float(h2["q90_abs_error_default"]),
        placeholder_estimated=float(h2["placeholder_u"]["estimated"]),
        placeholder_default=float(h2["placeholder_u"]["default"]),
        coverage=float(h2["pooled_coverage"]),
        coverage_by_profile={k: float(v) for k, v in h2["coverage_by_profile"].items()},
        top1_kept=float(h4["p_top1_kept"]),
        top1_thin_lead=_opt(h4, "p_kept_thin_lead"),
        top1_thick_lead=_opt(h4, "p_kept_thick_lead"),
        thin_lead_below=_opt(h4, "thin_lead_below"),
        h5_reduction={k: float(v) for k, v in (h5.get("mean_error_reduction") or {}).items()},
        h5_rows=int(tests["H5"]["n_rows"]),
        verdicts={name: t["verdict"] for name, t in tests.items()},
        rows_by_test={name: int(t["n_rows"]) for name, t in tests.items()},
        spearman_pooled=float(h3["spearman_rho_pooled"]),
        spearman_within_random_mix=float(h3["spearman_rho_within_random_mix"]),
        naive_default_share_rho=float(h3["naive_default_share_rho"]),
        factories_in_file=prov.get("data_log", {}).get("factories in file"),
        fuels=fuels,
        placeholder_status=prov["trust_config"]["status"],
    )


def _opt(block: dict, key: str) -> float | None:
    value = block.get(key)
    return None if value is None else float(value)


def load(path: Path) -> Headline:
    return headline(json.loads(path.read_text(encoding="utf-8")))
