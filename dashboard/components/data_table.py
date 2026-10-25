"""A plain data table in the product's look. Cells are text unless marked as trusted HTML.

Numbers are right-aligned, the first column is sticky, and every text value is escaped. A caller that
needs a badge or a link passes it as `Html`, built from escaped parts.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .markup import esc


@dataclass(frozen=True)
class Html:
    """Trusted markup for a cell (a badge, a mark). Build it from escaped parts."""

    markup: str


@dataclass(frozen=True)
class Column:
    title: str
    numeric: bool = False
    nowrap: bool = False
    note: str = ""  # a small line under the title (a unit, say)


def _cell(value: object) -> str:
    if isinstance(value, Html):
        return value.markup
    if value is None or value == "":
        return '<span class="eis-na">n/a</span>'
    return esc(value)


def table_html(
    columns: Sequence[Column], rows: Sequence[Sequence[object]], first_bold: bool = True
) -> str:
    head = "".join(
        f'<th class="{"firstcol" if i == 0 else ""}{" num" if c.numeric else ""}">'
        f"{esc(c.title)}{f'<small>{esc(c.note)}</small>' if c.note else ''}</th>"
        for i, c in enumerate(columns)
    )
    body = []
    for row in rows:
        cells = []
        for i, (c, value) in enumerate(zip(columns, row, strict=True)):
            cls = " ".join(
                x
                for x in (
                    "firstcol" if i == 0 else "",
                    "num" if c.numeric else "",
                    "nowrap" if c.nowrap else "",
                )
                if x
            )
            text = _cell(value)
            if i == 0 and first_bold and not isinstance(value, Html):
                text = f"<b>{text}</b>"
            cells.append(f'<td class="{cls}">{text}</td>')
        body.append(f"<tr>{''.join(cells)}</tr>")
    return (
        '<div class="eis-tablewrap"><table class="eis-table">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def name_cell(name: str, tag_html: str = "") -> Html:
    """A bold name, optionally followed by a badge (built from escaped parts)."""
    return Html(f"<b>{esc(name)}</b>" + (f" {tag_html}" if tag_html else ""))
