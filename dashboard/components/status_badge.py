"""Badges and status marks.

A data-class badge tells a reader how well a number is known. Each badge carries its word and an icon, so
colour is never the only signal. The classes are Measured, Estimated and Default; a Default is a generic
value used because nothing better was available.
"""

from __future__ import annotations

from .icons import STATUS_ICONS, icon
from .markup import attrs, esc

# data class -> (label, tone, icon, tooltip)
DATA_CLASSES = {
    "measured": (
        "Measured",
        "ok",
        "verified",
        "Directly metered, billed or weighed for the period (an electricity bill, a fuel invoice).",
    ),
    "estimated": (
        "Estimated",
        "info",
        "calculate",
        "Derived from a proxy: running hours times rated load, spend divided by a typical price, a stock difference.",
    ),
    "default": (
        "Default",
        "warn",
        "help",
        "A generic or sector-average value used because no data were available.",
    ),
}

BANDS = {
    "high": ("High trust", "ok"),
    "medium": ("Medium trust", "info"),
    "low": ("Low trust", "warn"),
    "not available": ("Not available", ""),
}


def data_class_badge(data_class: str) -> str:
    label, tone, glyph, tip = DATA_CLASSES.get(data_class, (data_class.capitalize(), "", "", ""))
    return badge(label, tone, glyph, tip)


def trust_band_badge(band: str) -> str:
    label, tone = BANDS.get(band, (band.capitalize(), ""))
    return badge(label, tone)


def badge(text: str, tone: str = "", glyph: str = "", tip: str = "") -> str:
    """A small labelled tag. `tone` is accent, info, warn, danger, ok or '' (neutral)."""
    mark = icon(glyph) if glyph else ""
    return f'<span class="eis-badge {esc(tone)}"{attrs(data_tip=tip)}>{mark}{esc(text)}</span>'


def status_mark(status: str, text: str) -> str:
    """An icon plus its word for a pass / attention / fail / info / n/a result."""
    css = status if status in STATUS_ICONS else "na"
    return f'<span class="eis-st {css}">{icon(STATUS_ICONS[css], fill=True)}{esc(text)}</span>'
