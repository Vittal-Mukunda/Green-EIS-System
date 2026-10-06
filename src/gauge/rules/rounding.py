"""Display rounding. The rules are applied to the numbers a model SEES, so the correct answer can be
derived exactly from the prompt text. Rounding is half-even to N significant figures."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

from gauge.kpi.formula import CONTEXT


def sig_round(value: Decimal, figures: int) -> Decimal:
    """Round to `figures` significant figures (half-even). Zero stays zero."""
    if value == 0:
        return Decimal(0)
    if figures < 1:
        raise ValueError("figures must be >= 1")
    exponent = value.adjusted() - figures + 1
    return value.quantize(Decimal(1).scaleb(exponent), rounding=ROUND_HALF_EVEN, context=CONTEXT)


def plain(value: Decimal) -> str:
    """Decimal text without an exponent, e.g. 1093, 0.1472, 58.4 (never 1.093E+3)."""
    text = format(value, "f")
    return "0" if Decimal(text) == 0 else text


def grouped(value: Decimal) -> str:
    """Plain text with thousands separators in the integer part: 623,812,700 or 88,511.5."""
    text = plain(value)
    whole, _, frac = text.partition(".")
    sign = "-" if whole.startswith("-") else ""
    digits = whole.lstrip("-")
    groups = f"{int(digits):,}" if digits else "0"
    return f"{sign}{groups}" + (f".{frac}" if frac else "")
