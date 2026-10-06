"""Evidence quality: can this company's numbers be trusted and checked? Shown prominently on the
company page, and as grouped checks on the compliance page.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .icons import STATUS_ICONS, icon
from .markup import esc


@dataclass
class Evidence:
    state: str  # ok, warn, fail, na
    title: str
    detail: str  # trusted HTML


def evidence_card_html(title: str, items: Sequence[Evidence], note: str = "") -> str:
    cells = "".join(
        f'<div class="eis-ev {esc(e.state)}">{icon(STATUS_ICONS.get(e.state, "info"), fill=True)}'
        f'<div><b>{esc(e.title)}</b><span class="d">{e.detail}</span></div></div>'
        for e in items
    )
    foot = f'<div class="eis-meta" style="margin-top:10px">{esc(note)}</div>' if note else ""
    return (
        f'<div class="eis-card eis-evidence"><div class="eis-card-head"><h3 class="eis-card-title">{esc(title)}</h3></div>'
        f'<div class="eis-evidence-grid">{cells}</div>{foot}</div>'
    )


@dataclass
class Check:
    status: str  # pass, attention, fail, info
    title: str
    found: str
    why: str = ""


def check_groups_html(groups: Sequence[tuple[str, Sequence[Check]]]) -> str:
    """Grouped disclosure checks. Group titles are plain headings (BRSR core disclosure, boundary, ...)."""
    out = []
    for title, checks in groups:
        rows = "".join(
            f'<div class="eis-check {esc(c.status)}">{icon(STATUS_ICONS.get(c.status, "info"), fill=True)}'
            f'<div><b>{esc(c.title)}</b><div class="d">{esc(c.found)}</div>'
            f"{'<div class=w>' + esc(c.why) + '</div>' if c.why else ''}</div></div>"
            for c in checks
        )
        out.append(f'<div class="eis-checkgroup"><div class="head">{esc(title)}</div>{rows}</div>')
    return "".join(out)
