"""The case table: one row per unit and energy item, the shape every data source is converted into.

| column       | meaning                                                                          |
|--------------|----------------------------------------------------------------------------------|
| unit_id      | one factory or audited unit                                                      |
| item_id      | a fuel id from the factor library, or ``grid_electricity``                       |
| quantity     | the reference quantity: kg for fuels, kWh for electricity (reported or measured) |
| value_inr    | what the unit spent on this item                                                 |
| scale        | the unit's size driver (output value or employees), for the Default proxy        |
| sector       | the group a Default value is borrowed from                                       |
| price_group  | the group a typical price is borrowed from (state and year)                      |
| cluster      | the bootstrap cluster (units sharing prices are not independent; use state-year) |
| synthetic    | True for generated test data                                                     |

The reference quantity is what the data source calls reported or measured. The study compares what a unit
without that record would derive (spend divided by a typical price; a sector-typical intensity times its
scale) against it. Whether the reference is metered or merely reported is a property of the source and is
stated in every result (RESEARCH_DESIGN section 7).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..factors import ELECTRICITY_ITEM, FactorLibrary, default_library

COLUMNS = (
    "unit_id",
    "item_id",
    "quantity",
    "value_inr",
    "scale",
    "sector",
    "price_group",
    "cluster",
    "synthetic",
)


class CaseError(ValueError):
    """The case table is not usable."""


def canonical_unit(item_id: str) -> str:
    return "kWh" if item_id == ELECTRICITY_ITEM else "kg"


@dataclass(frozen=True)
class Validation:
    cases: pd.DataFrame
    dropped: dict[str, int]  # reason -> rows removed


def validate(df: pd.DataFrame, library: FactorLibrary | None = None) -> Validation:
    """Check the columns and drop unusable rows, counting every drop (nothing disappears silently)."""
    library = library or default_library()
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise CaseError(f"case table is missing columns: {', '.join(missing)}")
    cases = df.loc[:, list(COLUMNS)].copy()
    dropped: dict[str, int] = {}

    def drop(mask: pd.Series, reason: str) -> None:
        nonlocal cases
        n = int(mask.sum())
        if n:
            dropped[reason] = dropped.get(reason, 0) + n
            cases = cases.loc[~mask]

    known = cases["item_id"].map(lambda i: i == ELECTRICITY_ITEM or library.is_fuel(i))
    drop(~known, "unknown item_id")
    for column in ("quantity", "value_inr", "scale"):
        cases[column] = pd.to_numeric(cases[column], errors="coerce")
        drop(~(cases[column] > 0), f"{column} missing or not positive")
    for column in ("unit_id", "sector", "price_group", "cluster"):
        drop(
            cases[column].isna() | (cases[column].astype(str).str.strip() == ""),
            f"{column} missing",
        )
    dup = cases.duplicated(["unit_id", "item_id"], keep=False)
    drop(dup, "duplicate unit and item")
    cases["synthetic"] = cases["synthetic"].astype(bool)
    if cases.empty:
        raise CaseError("no usable rows remain; dropped: " + str(dropped))
    return Validation(cases.reset_index(drop=True), dropped)


def load_csv(path: str) -> Validation:
    return validate(pd.read_csv(path))
