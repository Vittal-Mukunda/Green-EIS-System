"""Number formatting shared by the components: readable figures, never scientific notation."""

from __future__ import annotations

import pandas as pd


def fmt_number(value: float) -> str:
    """A number a person can read at a glance: separators, 3 to 4 significant figures, and never
    scientific notation."""
    if pd.isna(value):
        return "n/a"
    size = abs(value)
    if size >= 1000:
        return f"{value:,.0f}"
    if size >= 100:
        return f"{value:.0f}"
    if size >= 10:
        return f"{value:.1f}"
    if size >= 1:
        return f"{value:.2f}"
    if size >= 0.01:
        return f"{value:.3f}"
    return f"{value:.2g}"


def fmt_figure(value: float, unit: str) -> str:
    """A figure as text, without its unit: percentages to one decimal place (103.5, not 104)."""
    if pd.isna(value):
        return "not available"
    return f"{value:,.1f}" if unit.strip() == "%" else fmt_number(value)


def fmt_value(value: float, unit: str) -> str:
    """A figure with its unit: 103.5 %, 8.42 tCO2e."""
    return f"{fmt_figure(value, unit)} {unit}".strip() if not pd.isna(value) else "not available"


def fmt_t(value: object, places: int = 2) -> str:
    """Tonnes of CO2e with separators: 38.97, 1,204.51. Accepts a Decimal or a float; None is n/a."""
    if value is None:
        return "n/a"
    return f"{float(value):,.{places}f}"


def fmt_pct(fraction: object, places: int = 1) -> str:
    """A fraction as a percentage: 0.4853 becomes 48.5%."""
    if fraction is None:
        return "n/a"
    return f"{float(fraction) * 100:.{places}f}%"


def fmt_inr(value: object) -> str:
    """Rupees, whole numbers with separators."""
    if value is None:
        return "n/a"
    return f"{float(value):,.0f}"
