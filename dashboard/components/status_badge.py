"""Badges and position chips.

A position is where a figure sits among the companies of its own sector that pass the data checks. It
is not a rating. The six words below are the only ones the interface uses for a position, and each chip
carries its word, so colour is never the only signal.
"""

from __future__ import annotations

from gauge.viewdata import BAND_FLAT, DATA_CHECK

from .icons import STATUS_ICONS, icon
from .markup import attrs, esc

# band as stored by gauge.viewdata -> (label shown, css class)
POSITIONS = {
    "better third": ("Better third", "better"),
    "middle third": ("Middle third", "middle"),
    "weaker third": ("Weaker third", "weaker"),
    BAND_FLAT: ("No clear difference", "flat"),
    DATA_CHECK: ("Data check", "check"),
    "n/a": ("Too few to place", "na"),
}
POSITION_HELP = {
    "better": "Among the better third of its sector sample on this metric (a position, not a rating).",
    "middle": "In the middle third of its sector sample on this metric.",
    "weaker": "Among the weaker third of its sector sample on this metric (a position, not a rating).",
    "flat": "The sector's values are within 1% of their median, so a rank would carry little meaning.",
    "check": "The figure fails a data-quality check, so it is shown but not ranked. It is not a finding that the company misreported.",
    "na": "Fewer than three companies in the sector pass the checks, too few to place anyone.",
}


def position_label(band: str) -> str:
    return POSITIONS.get(band, (band.capitalize(), "na"))[0]


def position_chip(band: str, detail: str = "") -> str:
    """A chip such as 'Better third  2 of 5'."""
    label, css = POSITIONS.get(band, (band.capitalize(), "na"))
    extra = f' <span class="eis-muted">{esc(detail)}</span>' if detail else ""
    return f'<span class="eis-pos {css}"{attrs(data_tip=POSITION_HELP.get(css))}>{esc(label)}{extra}</span>'


def badge(text: str, tone: str = "", glyph: str = "", tip: str = "") -> str:
    """A small labelled tag. `tone` is accent, info, warn, danger, ok or '' (neutral)."""
    mark = icon(glyph) if glyph else ""
    return f'<span class="eis-badge {esc(tone)}"{attrs(data_tip=tip)}>{mark}{esc(text)}</span>'


def status_mark(status: str, text: str) -> str:
    """An icon plus its word for a pass / attention / fail / info / n/a result."""
    css = status if status in STATUS_ICONS else "na"
    return f'<span class="eis-st {css}">{icon(STATUS_ICONS[css], fill=True)}{esc(text)}</span>'
