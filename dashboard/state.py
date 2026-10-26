"""Session state for the unit being worked on, and the conversion from the entry table to activities.

The entry table is what the person types; `frame_to_activities` turns it into engine activities and
reports, row by row, anything it cannot calculate. A row with an error is left out of the footprint and
the pages say so; nothing is guessed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import pandas as pd
import streamlit as st

from greeneis.engine import Activity, EngineError, Footprint, calculate_activity
from greeneis.factors import ELECTRICITY_ITEM, default_library
from greeneis.trust import TrustConfig

COLUMNS = ["Item", "Name", "Quantity", "Unit", "Data class", "Cost (INR)", "Equipment"]
UNITS = ["kg", "t", "kt", "L", "kL", "kWh", "MWh"]
CLASS_LABELS = {"Measured": "measured", "Estimated": "estimated", "Default": "default"}
EQUIPMENT = [
    "",
    "boiler",
    "thermic_fluid_heater",
    "thermopac",
    "furnace",
    "kiln",
    "dg_set",
    "brick_kiln",
    "pottery_kiln",
    "jaggery_pan",
]
GRID_NAME = "Grid electricity"

BLANK_PERIOD = "Period 1"
EXAMPLE_NAME = "Illustrative factory"
EXAMPLE_PERIOD = "Example month"
EXAMPLE_ROWS = [  # the reference document's worked example (section 7): invented, not a real unit
    [GRID_NAME, "Grid electricity", 18000.0, "kWh", "Measured", 144000.0, ""],
    [
        "Coal (sub-bituminous, grade assumed)",
        "Coal (boiler)",
        10000.0,
        "kg",
        "Estimated",
        90000.0,
        "boiler",
    ],
    [
        "Diesel oil (HSDO / LDO)",
        "Diesel (generator and vehicle)",
        2000.0,
        "L",
        "Estimated",
        180000.0,
        "dg_set",
    ],
    ["Liquefied petroleum gas (LPG)", "LPG (heating)", 500.0, "kg", "Default", 50000.0, ""],
]


def load_example() -> None:
    """Replace the entered data with the labelled illustrative example (a test fixture, not a real unit)."""
    ss = st.session_state
    ss["bases"], ss["periods"], ss["sales"], ss["scenarios"] = {}, {}, {}, []
    replace_period(EXAMPLE_PERIOD, example_frame())
    ss["period"], ss["unit_name"] = EXAMPLE_PERIOD, EXAMPLE_NAME


def item_names() -> dict[str, str]:
    """Display name -> library item id, grid electricity first."""
    lib = default_library()
    return {GRID_NAME: ELECTRICITY_ITEM, **{f.name: f.id for f in lib.fuels}}


def example_frame() -> pd.DataFrame:
    return pd.DataFrame(EXAMPLE_ROWS, columns=COLUMNS)


def empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Item": pd.Series(dtype="object"),
            "Name": pd.Series(dtype="object"),
            "Quantity": pd.Series(dtype="float"),
            "Unit": pd.Series(dtype="object"),
            "Data class": pd.Series(dtype="object"),
            "Cost (INR)": pd.Series(dtype="float"),
            "Equipment": pd.Series(dtype="object"),
        }
    )


def init_state() -> None:
    """`bases` holds what was loaded or uploaded and is never rewritten by the editor (feeding an
    editor's output back as its input loses or doubles edits); `periods` holds the current, edited
    tables that every page reads."""
    ss = st.session_state
    ss.setdefault("unit_name", "")
    ss.setdefault("bases", {BLANK_PERIOD: empty_frame()})
    ss.setdefault("periods", {BLANK_PERIOD: empty_frame()})
    ss.setdefault("period", BLANK_PERIOD)
    ss.setdefault("sales", {})  # period -> sales in INR lakh (optional)
    ss.setdefault("editor_version", 0)
    ss.setdefault("scenarios", [])
    ss.setdefault("scope", "This period")


def replace_period(period: str, frame: pd.DataFrame) -> None:
    """Load a table as a period's data and reset its editor."""
    ss = st.session_state
    ss["bases"][period] = frame.reset_index(drop=True)
    ss["periods"][period] = frame.reset_index(drop=True)
    ss["editor_version"] += 1


def add_period(label: str) -> bool:
    ss = st.session_state
    label = label.strip()
    if not label or label in ss["periods"]:
        return False
    replace_period(label, empty_frame())
    ss["period"] = label
    return True


def all_periods_csv() -> str:
    """Every period's table as one CSV, with a Period column, for download."""
    frames = []
    for period, frame in st.session_state["periods"].items():
        f = frame.copy()
        f.insert(0, "Period", period)
        frames.append(f)
    if not frames:
        return ""
    return pd.concat(frames, ignore_index=True).to_csv(index=False)


def load_csv(raw: bytes) -> tuple[int, str | None]:
    """Replace the entered data with an uploaded CSV. Returns (periods loaded, error message)."""
    import io

    try:
        df = pd.read_csv(io.BytesIO(raw))
    except Exception as exc:  # unreadable file: say so, change nothing
        return 0, f"The file could not be read as a CSV ({exc})."
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        return 0, "The CSV is missing these columns: " + ", ".join(missing) + "."
    if "Period" not in df.columns:
        df["Period"] = "Uploaded"
    ss = st.session_state
    ss["bases"], ss["periods"], ss["sales"], ss["scenarios"] = {}, {}, {}, []
    for period, grp in df.groupby("Period", sort=False):
        replace_period(str(period), grp[COLUMNS])
    ss["period"] = next(iter(ss["periods"]))
    return len(ss["periods"]), None


def is_example() -> bool:
    ss = st.session_state
    periods = ss["periods"]
    return (
        ss["unit_name"] == EXAMPLE_NAME
        and list(periods) == [EXAMPLE_PERIOD]
        and periods[EXAMPLE_PERIOD].reset_index(drop=True).equals(example_frame())
    )


def _blank(value: object) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value)) or value == ""


def _decimal(value: object) -> Decimal | None:
    if _blank(value):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def frame_to_activities(
    frame: pd.DataFrame, number_from: int = 1
) -> tuple[list[Activity], list[str], list[str]]:
    """Activities for every row that can be calculated, plus an error for each row that cannot and
    warnings for things that are allowed but worth knowing."""
    names = item_names()
    activities: list[Activity] = []
    errors: list[str] = []
    warnings: list[str] = []
    used: dict[str, int] = {}
    for i, row in enumerate(frame.to_dict("records"), start=number_from):
        if all(_blank(row.get(c)) for c in COLUMNS):
            continue
        where = f"Row {i}"
        item_name = row.get("Item")
        if _blank(item_name) or item_name not in names:
            errors.append(f"{where}: choose an item.")
            continue
        quantity = _decimal(row.get("Quantity"))
        if quantity is None:
            errors.append(f"{where}: enter a quantity.")
            continue
        unit = row.get("Unit")
        if _blank(unit):
            errors.append(f"{where}: choose a unit.")
            continue
        label = str(row.get("Name") or "").strip() or str(item_name)
        count = used.get(label, 0) + 1
        used[label] = count
        if count > 1:
            warnings.append(
                f"{where}: the name '{label}' is already used; it was renamed '{label} ({count})'."
            )
            label = f"{label} ({count})"
        raw_class = row.get("Data class")
        if _blank(raw_class) or raw_class not in CLASS_LABELS:
            data_class = "default"
            warnings.append(
                f"{where}: no data class chosen, so '{label}' is treated as Default (the least trusted)."
            )
        else:
            data_class = CLASS_LABELS[raw_class]
        cost = _decimal(row.get("Cost (INR)"))
        equipment = "" if _blank(row.get("Equipment")) else str(row["Equipment"])
        try:
            activity = Activity(
                item_id=names[item_name],
                quantity=quantity,
                unit=str(unit),
                data_class=data_class,
                cost_inr=cost,
                label=label,
                equipment=equipment,
            )
            calculate_activity(activity)
        except EngineError as exc:
            errors.append(f"{where}: {exc}")
            continue
        activities.append(activity)
    return activities, errors, warnings


@dataclass
class Context:
    """What every page needs, built once per run."""

    unit_name: str
    period: str
    scope: str
    activities: list[Activity]
    footprint: Footprint | None
    errors: list[str]
    warnings: list[str]
    cfg: TrustConfig
    sales_lakh: Decimal | None
    is_example: bool

    @property
    def has_data(self) -> bool:
        return bool(self.activities)


_CLASS_RANK = {"measured": 2, "estimated": 1, "default": 0}


def aggregate(activities: list[Activity]) -> list[Activity]:
    """Merge lines with the same item, name and equipment (the same activity in different periods).
    Quantities are summed in the common unit; cost is summed, or unknown if any line lacks one; the data
    class is the least trusted of the lines, so a merged number is never trusted more than its weakest part."""
    from greeneis.engine import canonical_quantity

    merged: dict[tuple[str, str, str], Activity] = {}
    for a in activities:
        qty, unit = canonical_quantity(a)
        key = (a.item_id, a.label, a.equipment)
        if key not in merged:
            merged[key] = Activity(
                item_id=a.item_id,
                quantity=qty,
                unit=unit,
                data_class=a.data_class,
                cost_inr=a.cost_inr,
                label=a.label,
                equipment=a.equipment,
                grid_id=a.grid_id,
            )
            continue
        m = merged[key]
        cost = None if m.cost_inr is None or a.cost_inr is None else m.cost_inr + a.cost_inr
        worst = min(m.data_class, a.data_class, key=lambda c: _CLASS_RANK[c])
        merged[key] = Activity(
            item_id=m.item_id,
            quantity=m.quantity + qty,
            unit=unit,
            data_class=worst,
            cost_inr=cost,
            label=m.label,
            equipment=m.equipment,
            grid_id=m.grid_id,
        )
    return list(merged.values())


def build_context() -> Context:
    """Read the session and build what every page needs."""
    from greeneis.engine import calculate

    ss = st.session_state
    periods = ss["periods"]
    period = ss["period"] if ss["period"] in periods else next(iter(periods))
    many = len(periods) > 1
    scope = ss["scope"] if many else "This period"
    chosen = list(periods) if scope == "All periods entered" else [period]

    activities: list[Activity] = []
    errors: list[str] = []
    warnings: list[str] = []
    sales = Decimal(0)
    have_sales = False
    for p in chosen:
        a, e, w = frame_to_activities(periods[p])
        prefix = f"{p}, " if len(chosen) > 1 else ""
        activities += a
        errors += [prefix + x for x in e]
        warnings += [prefix + x for x in w]
        value = ss["sales"].get(p)
        if value:
            sales += Decimal(str(value))
            have_sales = True
    if len(chosen) > 1:
        activities = aggregate(activities)
    footprint = calculate(activities) if activities else None
    label = "all periods entered" if len(chosen) > 1 else period
    return Context(
        unit_name=ss["unit_name"] or "Unnamed unit",
        period=label,
        scope=scope,
        activities=activities,
        footprint=footprint,
        errors=errors,
        warnings=warnings,
        cfg=TrustConfig(),
        sales_lakh=sales if have_sales else None,
        is_example=is_example(),
    )
