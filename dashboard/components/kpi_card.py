"""KPI figures: the dataset strip, single KPI cards and the company KPI profile card."""

from __future__ import annotations

from collections.abc import Sequence

from .markup import esc, render


def stat_strip_html(items: Sequence[tuple[str, str, str]]) -> str:
    """One panel of dataset-level figures. Each item is (label, value, note)."""
    cells = "".join(
        f'<div><div class="eis-kpi"><span class="eis-kpi-label">{esc(label)}</span>'
        f'<span class="eis-kpi-value">{esc(value)}</span>'
        f'<span class="eis-kpi-sub">{esc(note)}</span></div></div>'
        for label, value, note in items
    )
    return f'<div class="eis-strip" style="--n:{len(items)}">{cells}</div>'


def stat_strip(items: Sequence[tuple[str, str, str]]) -> None:
    render(stat_strip_html(items))


def kpi_profile_card_html(
    label: str,
    value: str,
    unit: str,
    chips: str = "",
    vs_median: str = "",
    foot_left: str = "",
    foot_right: str = "",
    tone: str = "",
) -> str:
    """A company's figure for one KPI: value and unit, position chip, distance from the sample median
    and the change on the previous year. `chips`, `vs_median` and the foot items are trusted HTML built
    by the caller from escaped parts."""
    foot = (
        f'<div class="foot"><span>{foot_left}</span><span>{foot_right}</span></div>'
        if foot_left or foot_right
        else ""
    )
    return (
        f'<div class="eis-kpi-card"><div class="eis-kpi {esc(tone)}">'
        f'<span class="eis-kpi-label">{esc(label)}</span>'
        f'<span class="eis-kpi-value">{esc(value)}</span><span class="eis-kpi-unit">{esc(unit)}</span></div>'
        f'<div class="eis-kpi-chips">{chips}</div>'
        f"{'<div class=vs>' + vs_median + '</div>' if vs_median else ''}{foot}</div>"
    )


def chain_strip_html(items: Sequence[tuple[str, str, str, str]]) -> str:
    """The chain of assurance as one strip, each cell leading to the next.
    Each item is (icon name, label, value, note)."""
    from .icons import icon

    cells = "".join(
        f'<div><div class="eis-kpi"><span class="eis-kpi-label">{icon(glyph)}{esc(label)}</span>'
        f'<span class="eis-kpi-value">{esc(value)}</span>'
        f'<span class="eis-kpi-sub">{esc(note)}</span></div></div>'
        for glyph, label, value, note in items
    )
    return f'<div class="eis-strip chain" style="--n:{len(items)}">{cells}</div>'
