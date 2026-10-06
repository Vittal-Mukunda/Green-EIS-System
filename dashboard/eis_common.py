"""What every evidence page shares: the run context, company naming, the page header and small helpers.

Nothing here calls a model. Pages put a unit on every number, show companies by their real names
unless the sidebar switch asks for the masked codes, and open with the same header.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import streamlit as st
from components.filters import year_picker as _year_picker
from components.markup import esc, render
from components.navigation import (  # noqa: F401  (re-exported for the pages)
    open_company,
    open_filing,
    open_page,
    open_sector,
    open_verification,
)
from components.page_header import page_header
from components.people import People
from components.status_badge import POSITIONS, position_chip
from sqlalchemy import Engine

from gauge import vocab
from gauge.config import IndicatorsConfig, StudyConfig
from gauge.db.session import session_scope
from gauge.viewdata import company_directory, pretty_unit

STATUS_TEXT = {
    "pass": "✔ Pass",
    "attention": "▲ Attention",
    "fail": "✖ Fail",
    "info": "ℹ Info",
    "n/a": "– n/a",
}
CROSS_SECTOR_WARNING = (
    "These companies are in different sectors, so their figures are not like for like. A cement "
    "works and a software company differ by orders of magnitude on most of these metrics because of "
    "what they do, not because one is better or worse. Direct comparison may not be meaningful."
)


@dataclass
class Ctx:
    """What every page needs from the running app."""

    cfg: StudyConfig
    engine: Engine
    indicators: IndicatorsConfig
    real_names: bool
    pages: list[str]


def people_of(ctx: Ctx) -> People:
    with session_scope(ctx.engine) as s:
        return People(company_directory(s), ctx.real_names)


def header(
    title: str,
    what: str,
    compared: str | None = None,
    read: str | None = None,
    page: str | None = None,
    trail: tuple[str, ...] = (),
) -> None:
    """The same opening on every page: breadcrumb, title, what it shows, what is being compared, how
    to read it."""
    page_header(title, what, compared, read, page=page, trail=trail)


def section(title: str, note: str = "") -> None:
    """A section heading with an optional right-hand note (plain text)."""
    right = f'<span class="eis-section-note">{esc(note)}</span>' if note else ""
    render(f'<div class="eis-section"><h3>{esc(title)}</h3>{right}</div>')


def jump_to_company(ctx: Ctx, people: People, codes, key: str) -> None:
    """Drill down: pick one of `codes` and open its profile."""
    present = sorted({c for c in codes if c in people.rows}, key=people.label)
    if "Companies" not in ctx.pages or not present:
        return
    left, right = st.columns([3, 1], vertical_alignment="bottom")
    pick = left.selectbox(
        "Open a company's profile", present, format_func=people.label, key=f"{key}_pick"
    )
    right.button("Open", key=f"{key}_open", on_click=open_company, args=(pick,))


def year_picker(ctx: Ctx, years: list[str], key: str, label: str = "Fiscal year") -> str:
    return _year_picker(ctx.cfg.study.analysis_fy, years, key, label)


def colour_key() -> None:
    """The legend for position chips: the six words, once, with the reminder that positions are not
    ratings."""
    chips = "".join(
        position_chip(band)
        for band in (
            "better third",
            "middle third",
            "weaker third",
            "no clear difference",
            "data check",
        )
    )
    render(
        f'<div class="eis-legend"><b>Position within the sector</b>{chips}'
        '<span class="eis-legend-note">Colours show where a figure sits among companies in the same '
        "sector that pass the data checks. They are not environmental ratings, ESG scores or a judgement "
        "of any company. A data check is a figure to verify: it is shown, never ranked.</span></div>"
    )


def change_text(change: float, movement: str) -> str:
    if pd.isna(change):
        return "not available"
    return f"{round(change, 1) + 0.0:+.1f}% ({movement})"


def kpi_title(label: str, unit: str) -> str:
    return f"{label} ({pretty_unit(unit)})"


__all__ = [
    "CROSS_SECTOR_WARNING",
    "POSITIONS",
    "STATUS_TEXT",
    "Ctx",
    "People",
    "change_text",
    "colour_key",
    "header",
    "jump_to_company",
    "kpi_title",
    "open_company",
    "open_filing",
    "open_page",
    "open_sector",
    "open_verification",
    "people_of",
    "section",
    "vocab",
    "year_picker",
]
