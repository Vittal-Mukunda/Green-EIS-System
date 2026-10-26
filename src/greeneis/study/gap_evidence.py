"""Aggregate evidence from the ASI case table for the research gaps the study harness does not cover.

The study harness (`run.py`) tests the trust labels (H1-H5). Three of the research gaps need descriptive
facts about the same real factories that the harness does not report:

- **Gap 1, reporting coverage:** how many small factories report a usable fuel quantity, and how many
  report spend on fuels that carry no quantity (so a quantity cannot be recovered from the return).
- **Gap 3, hotspot structure:** among factories with two or more tracked fuels, how large the top source's
  share is, how often the lead is thin, and which fuel leads.
- **Gap 4, cost link:** for each fuel, the share of reported spend against the share of calculated
  emissions, and the rupees paid per tonne of CO2e.

Emissions use the engine and the factor library, the same as everywhere else. The quantity is what the
factory reported in its return (not metered), so every figure is "as reported". Only aggregates are
written: counts, shares and quantiles, never a factory-level row (the portal's terms are unread, V-18).

    python -m greeneis.study.gap_evidence --path C:/Users/vitta/greeneis-data/asi/ASI24m.TXT
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

from ..engine import Activity, calculate_activity
from ..factors import default_library
from . import asi

THIN_LEAD_BELOW = 0.10  # same threshold as H4 (placeholder, fixed before any real data; V-26)

# Fixed ASI lines that carry a value but never a quantity (checked on the real file, asi.py docstring).
NO_QUANTITY_LINES = {
    "9990600": "Petrol, diesel and oil",
    "9920400": "Other fuel",
    "9990400": "Electricity generated and consumed by the factory",
}


def _co2e_t(item_id: str, quantity: float) -> float:
    """Tonnes CO2e for one reported quantity (kWh for electricity, kg for fuels), by the engine."""
    unit = "kWh" if item_id == "grid_electricity" else "kg"
    activity = Activity(item_id, Decimal(str(quantity)), unit, "estimated")
    return float(calculate_activity(activity, default_library()).co2e_t)


def with_emissions(cases: pd.DataFrame) -> pd.DataFrame:
    """The case table with a `co2e_t` column. Records with no calculable factor are not expected here
    (the table only holds electricity, coal and gas) and would raise."""
    out = cases.copy()
    out["co2e_t"] = [_co2e_t(i, q) for i, q in zip(out["item_id"], out["quantity"], strict=True)]
    return out


def fuel_cost_link(cases: pd.DataFrame) -> list[dict]:
    """Per fuel: records, spend and emissions totals and shares, rupees per tCO2e (all records pooled,
    and the median/quartiles of the per-record figure)."""
    df = with_emissions(cases)
    total_spend, total_co2e = df["value_inr"].sum(), df["co2e_t"].sum()
    rows = []
    for item, g in df.groupby("item_id"):
        per_record = g.loc[g["co2e_t"] > 0, "value_inr"] / g.loc[g["co2e_t"] > 0, "co2e_t"]
        q1, med, q3 = (
            np.quantile(per_record, [0.25, 0.5, 0.75]) if len(per_record) else (np.nan,) * 3
        )
        rows.append(
            {
                "item": item,
                "records": int(len(g)),
                "spend_inr": float(g["value_inr"].sum()),
                "co2e_t": float(g["co2e_t"].sum()),
                "spend_share": float(g["value_inr"].sum() / total_spend),
                "co2e_share": float(g["co2e_t"].sum() / total_co2e),
                "inr_per_tco2e_pooled": float(g["value_inr"].sum() / g["co2e_t"].sum()),
                "inr_per_tco2e_q25": float(q1),
                "inr_per_tco2e_median": float(med),
                "inr_per_tco2e_q75": float(q3),
            }
        )
    return sorted(rows, key=lambda r: -r["co2e_t"])


def hotspot_structure(cases: pd.DataFrame, thin_below: float = THIN_LEAD_BELOW) -> dict:
    """Among factories with two or more tracked fuels: the top source's share, the lead over the second,
    how often the lead is thin, which fuel leads, and how often the biggest rupee item is not the biggest
    emitter. A factory with one fuel has nothing to rank and is only counted."""
    df = with_emissions(cases)
    per_unit = df.groupby("unit_id")["item_id"].nunique()
    multi_ids = per_unit[per_unit >= 2].index
    top_share, lead, top_item, cost_differs = [], [], [], []
    for _, g in df[df["unit_id"].isin(multi_ids)].groupby("unit_id"):
        by_emission = g.sort_values(["co2e_t", "item_id"], ascending=[False, True])
        shares = by_emission["co2e_t"] / by_emission["co2e_t"].sum()
        top_share.append(float(shares.iloc[0]))
        lead.append(float(shares.iloc[0] - shares.iloc[1]))
        top_item.append(by_emission["item_id"].iloc[0])
        top_cost = g.sort_values(["value_inr", "item_id"], ascending=[False, True])["item_id"].iloc[
            0
        ]
        cost_differs.append(top_cost != by_emission["item_id"].iloc[0])
    n = len(top_share)
    out: dict = {
        "factories_with_a_fuel": int(per_unit.size),
        "single_fuel_factories": int((per_unit == 1).sum()),
        "multi_fuel_factories": n,
        "thin_lead_below": thin_below,
    }
    if n:
        q1, med, q3 = np.quantile(top_share, [0.25, 0.5, 0.75])
        out |= {
            "top_share_q25": float(q1),
            "top_share_median": float(med),
            "top_share_q75": float(q3),
            "lead_median": float(np.median(lead)),
            "thin_lead_factories": int(sum(x < thin_below for x in lead)),
            "top_item_counts": {k: int(v) for k, v in pd.Series(top_item).value_counts().items()},
            "biggest_cost_not_biggest_emitter": int(sum(cost_differs)),
        }
    return out


def reporting_coverage(blocks: asi.Blocks, max_employees: int, cases: pd.DataFrame) -> dict:
    """How many small factories report what: a usable fuel quantity, spend on a line with no quantity,
    both, or neither. Counted over the same population the study starts from."""
    small = asi.small_factories(blocks, max_employees)
    ids = set(small["dsl"])
    h = blocks.h[blocks.h["dsl"].isin(ids)].copy()
    h["item"] = h["item"].astype(str).str.strip()
    usable = {u.rsplit("-", 1)[1] for u in cases["unit_id"].unique()}
    lines = {}
    no_qty_units: set[str] = set()
    for code, name in NO_QUANTITY_LINES.items():
        units = set(h.loc[(h["item"] == code) & (h["value"] > 0), "dsl"])
        lines[name] = len(units)
        no_qty_units |= units
    return {
        "small_factories": len(ids),
        "usable_quantity": len(usable),
        "no_quantity_lines": lines,
        "spend_without_quantity_any_line": len(no_qty_units),
        "usable_and_spend_without_quantity": len(usable & no_qty_units),
        "spend_without_quantity_only": len(no_qty_units - usable),
        "neither": len(ids - usable - no_qty_units),
    }


def compute(blocks: asi.Blocks, max_employees: int = 50, gas_item: str = "lpg") -> dict:
    built = asi.build_cases(blocks, max_employees, gas_item)
    cases = built.cases
    return {
        "provenance": {
            "source": f"ASI {built.log['round']}, gas as {gas_item}, up to {max_employees} persons",
            "synthetic": False,
            "reference_quantity": "reported by the factory in the ASI return (purchase records), "
            "not metered",
            "created_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "aggregates_only": True,
            "data_log": {k: v for k, v in built.log.items()},
        },
        "coverage": reporting_coverage(blocks, max_employees, cases),
        "cost_link": fuel_cost_link(cases),
        "hotspots": hotspot_structure(cases),
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--path", required=True, help="merged ASI file (ASI24m.TXT)")
    ap.add_argument("--max-employees", type=int, default=50)
    ap.add_argument("--out", default="outputs/gap_evidence_asi_2023-24.json")
    args = ap.parse_args(argv)
    result = compute(asi.read_blocks(args.path), args.max_employees)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes((json.dumps(result, indent=2) + "\n").encode("utf-8"))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
