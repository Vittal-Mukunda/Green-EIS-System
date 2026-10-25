"""Read the ASI (Annual Survey of Industries) merged unit-level file and build the study's case table.

Source: MoSPI microdata catalogue, ASI 2023-24 (file ASI24m.TXT, fixed width, 206 characters per record,
layout in Data_Structure_ASI_2023_24.pdf). Only three blocks are used:

- **Block A** (identification): state (A7), industry code as per return (A5, 5-digit NIC-2008), status of
  unit (A12; 1 = open), scheme (census or sample)
- **Block E** (employment): serial 10 is the total number of persons worked (E_I6)
- **Block H** (indigenous input items): item code (NPCMS), unit code, quantity, purchase value, rate

The schedule gives three fixed fuel lines with a quantity: electricity purchased and consumed (9990500,
kWh), coal consumed (9990700, tonnes) and gas consumed (9990900, kg). The lines for petrol/diesel/oil
(9990600), other fuel (9920400) and own-generated electricity (9990400) carry a value but never a quantity,
so they cannot be used (checked on the real file: 0 usable rows each).

Decisions fixed **before** the first look at any outcome (RESEARCH_DESIGN section 10):

- open factories only (status 1)
- small factories only: total persons worked at most `max_employees` (placeholder 50)
- the Default proxy's scale is the number of persons, not cost of production (which contains the fuel bill
  being predicted)
- the sector for a Default intensity is the 2-digit NIC division of the return code
- price group and bootstrap cluster are the state (the file holds one year)
- "gas consumed" is mapped to LPG by default (the schedule does not say whether it is LPG or natural gas;
  `gas_item="natural_gas"` is the pre-declared sensitivity run)
- the survey multiplier is ignored (errors are not population-weighted)
- the reference quantity is what the factory reported; it is not metered (stated in every result)
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

ROUND = "2023-24"
OPEN_STATUS = 1
TOTAL_PERSONS_SERIAL = 10

# (name, start, end) as 0-based, end-exclusive character positions in the 206-character record
COLUMNS = {
    "A": [
        ("dsl", 4, 10),
        ("scheme", 15, 16),
        ("nic5", 20, 25),
        ("state", 25, 27),
        ("sector", 29, 30),
        ("status", 37, 39),
        ("costop", 90, 104),
        ("mult", 107, 121),
    ],
    "E": [("dsl", 4, 10), ("sl", 10, 12), ("persons", 38, 46)],
    "H": [
        ("dsl", 4, 10),
        ("sl", 10, 13),
        ("item", 13, 20),
        ("unit", 20, 23),
        ("qty", 23, 37),
        ("value", 37, 51),
        ("rate", 51, 65),
    ],
}

# NPCMS fixed lines -> {unit code: factor to the canonical unit (kWh for electricity, kg for fuels)}
UNIT_CODES = {28: "K. Watt", 13: "Megawatt", 27: "Tonne", 9: "Kg"}
FIXED_LINES = {
    "9990500": ("grid_electricity", {28: 1.0, 13: 1000.0}),
    "9990700": ("coal", {27: 1000.0, 9: 1.0}),
    "9990900": (None, {9: 1.0, 27: 1000.0}),  # gas: item chosen by the caller
}


@dataclass(frozen=True)
class Blocks:
    a: pd.DataFrame
    e: pd.DataFrame
    h: pd.DataFrame


@dataclass
class CaseBuild:
    cases: pd.DataFrame
    log: dict[str, int | str] = field(default_factory=dict)


def _frame(lines: list[str], block: str, dtypes: dict[str, type]) -> pd.DataFrame:
    spec = COLUMNS[block]
    return pd.read_fwf(
        io.StringIO("".join(lines)),
        colspecs=[(s, e) for _, s, e in spec],
        names=[n for n, _, _ in spec],
        dtype=dtypes,
        header=None,
    )


def read_blocks(path: str | Path) -> Blocks:
    """Parse Blocks A, E and H from the merged file. The file is read once, line by line."""
    lines: dict[str, list[str]] = {"A": [], "E": [], "H": []}
    with open(path, encoding="latin-1") as handle:
        for line in handle:
            block = line[2:4].strip()
            if block in lines:
                lines[block].append(line)
    if not all(lines.values()):
        missing = [b for b, rows in lines.items() if not rows]
        raise ValueError(
            f"no records for block(s) {', '.join(missing)}; is this the merged ASI file?"
        )
    str_cols = {"dsl": str}
    return Blocks(
        a=_frame(lines["A"], "A", {**str_cols, "nic5": str, "state": str}),
        e=_frame(lines["E"], "E", str_cols),
        h=_frame(lines["H"], "H", {**str_cols, "item": str}),
    )


def build_cases(
    blocks: Blocks,
    max_employees: int = 50,
    gas_item: str = "lpg",
    year: str = ROUND,
) -> CaseBuild:
    """The case table (see study.cases) from the three blocks, with a count of everything left out."""
    if gas_item not in ("lpg", "natural_gas"):
        raise ValueError("gas_item must be 'lpg' or 'natural_gas'")
    log: dict[str, int | str] = {
        "round": year,
        "max_employees": max_employees,
        "gas_item": gas_item,
    }
    a = blocks.a.copy()
    log["factories in file"] = len(a)
    a = a[a["status"] == OPEN_STATUS]
    log["open factories"] = len(a)

    persons = blocks.e[blocks.e["sl"] == TOTAL_PERSONS_SERIAL].set_index("dsl")["persons"]
    a = a.join(persons.rename("employees"), on="dsl")
    a = a[a["employees"].notna() & (a["employees"] > 0)]
    log["open with persons recorded"] = len(a)
    a = a[a["employees"] <= max_employees]
    log["small (persons <= max_employees)"] = len(a)

    a["nic5"] = a["nic5"].astype(str).str.strip()
    division = a["nic5"].str[:2]
    usable_nic = division.str.fullmatch(r"\d\d") & (division != "99")
    log["dropped: industry code unusable"] = int((~usable_nic).sum())
    a = a[usable_nic]
    a["sector"] = "NIC" + a["nic5"].str[:2]

    h = blocks.h.copy()
    h["item"] = h["item"].astype(str).str.strip()
    h = h[h["item"].isin(FIXED_LINES) & (h["qty"] > 0) & (h["value"] > 0)]
    h = h.merge(a[["dsl", "state", "employees", "sector"]], on="dsl", how="inner")

    rows = []
    unsupported = 0
    for _, r in h.iterrows():
        item, factors = FIXED_LINES[r["item"]]
        item = item or gas_item
        factor = factors.get(int(r["unit"]))
        if factor is None:
            unsupported += 1
            continue
        rows.append(
            {
                "unit_id": f"ASI{year}-{r['dsl']}",
                "item_id": item,
                "quantity": float(r["qty"]) * factor,
                "value_inr": float(r["value"]),
                "scale": float(r["employees"]),
                "sector": r["sector"],
                "price_group": f"{r['state']}-{year}",
                "cluster": f"{r['state']}-{year}",
                "synthetic": False,
            }
        )
    log["dropped: unit code not convertible"] = unsupported
    cases = pd.DataFrame(rows)
    log["item records"] = len(cases)
    if len(cases):
        log["factories with at least one item"] = int(cases["unit_id"].nunique())
        for item, n in cases["item_id"].value_counts().items():
            log[f"records: {item}"] = int(n)
        per_unit = cases.groupby("unit_id")["item_id"].nunique()
        log["factories with two or more items"] = int((per_unit >= 2).sum())
        log["clusters (states)"] = int(cases["cluster"].nunique())
    return CaseBuild(cases, log)
