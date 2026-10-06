"""Matrix and side-by-side tables: the KPI scorecard and the company comparison.

Each cell shows a figure with its position word. Unit and direction ("lower is better") sit in the
column header, so a number is never shown without its unit.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from .markup import esc
from .status_badge import POSITION_HELP, POSITIONS


@dataclass
class Cell:
    """One figure in a matrix: its text, the position word, and a tooltip with the detail."""

    value: str = ""
    band: str = ""
    place: str = ""  # "2 of 5"
    tip: str = ""
    empty: bool = False


def position_cell_html(cell: Cell) -> str:
    if cell.empty:
        return (
            '<div class="eis-cell na" tabindex="0" data-tip="No figure is loaded for this company, metric and year.">'
            '<span class="v">not loaded</span><span class="p">no figure</span></div>'
        )
    label, css = POSITIONS.get(cell.band, (cell.band.capitalize(), "na"))
    word = label if css in ("check", "flat", "na") or not cell.place else f"{label} · {cell.place}"
    tip = cell.tip or POSITION_HELP.get(css, "")
    return (
        f'<div class="eis-cell {css}" tabindex="0" data-tip="{esc(tip)}">'
        f'<span class="v">{esc(cell.value)}</span><span class="p">{esc(word)}</span></div>'
    )


@dataclass
class MatrixColumn:
    label: str
    unit: str = ""
    note: str = ""  # "lower is better"


@dataclass
class MatrixRow:
    label: str
    sub: str = ""
    cells: list[Cell] = field(default_factory=list)
    extra: str = ""  # trusted HTML for a trailing column


@dataclass
class MatrixGroup:
    title: str
    rows: list[MatrixRow]


def scorecard_html(
    groups: Sequence[MatrixGroup], columns: Sequence[MatrixColumn], extra_header: str = ""
) -> str:
    """Companies down the side, grouped by sector, KPIs across."""
    head = "".join(
        f"<th>{esc(c.label)}<small>{esc(c.unit)}{' · ' + esc(c.note) if c.note else ''}</small></th>"
        for c in columns
    )
    span = len(columns) + 1 + (1 if extra_header else 0)
    body = []
    for group in groups:
        body.append(f'<tr class="grp"><td colspan="{span}">{esc(group.title)}</td></tr>')
        for row in group.rows:
            cells = "".join(f"<td>{position_cell_html(c)}</td>" for c in row.cells)
            extra = f"<td class='nowrap'>{row.extra}</td>" if extra_header else ""
            sub = f'<span class="sub">{esc(row.sub)}</span>' if row.sub else ""
            body.append(
                f'<tr><td class="firstcol"><b>{esc(row.label)}</b>{sub}</td>{cells}{extra}</tr>'
            )
    extra_th = f"<th>{esc(extra_header)}</th>" if extra_header else ""
    return (
        '<div class="eis-tablewrap"><table class="eis-table">'
        f'<thead><tr><th class="firstcol">Company</th>{head}{extra_th}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


@dataclass
class CompareRow:
    metric: str
    unit: str
    note: str  # "lower is better"
    cells: list[Cell]
    best: str = ""


def compare_html(people: Sequence[tuple[str, str]], rows: Sequence[CompareRow]) -> str:
    """Selected companies as columns, metrics as rows. `people` is (name, sector) per column."""
    head = "".join(f"<th>{esc(name)}<small>{esc(sector)}</small></th>" for name, sector in people)
    first = [
        '<tr class="grp"><td>Sector</td>'
        + "".join(f"<td>{esc(sector)}</td>" for _name, sector in people)
        + "<td></td></tr>"
    ]
    body = []
    for r in rows:
        cells = "".join(f"<td>{position_cell_html(c)}</td>" for c in r.cells)
        body.append(
            f'<tr><td class="firstcol"><b>{esc(r.metric)}</b>'
            f'<span class="sub">{esc(r.unit)} · {esc(r.note)}</span></td>{cells}'
            f'<td class="nowrap">{esc(r.best) if r.best else "<span class=eis-na>none ranked</span>"}</td></tr>'
        )
    return (
        '<div class="eis-tablewrap"><table class="eis-table">'
        f'<thead><tr><th class="firstcol">Metric</th>{head}<th>Best of those compared</th></tr></thead>'
        f"<tbody>{''.join(first)}{''.join(body)}</tbody></table></div>"
    )
