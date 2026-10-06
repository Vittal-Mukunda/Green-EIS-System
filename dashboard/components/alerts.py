"""Callouts: short, labelled messages that sit in the flow of a page."""

from __future__ import annotations

import streamlit as st

from .icons import icon
from .markup import esc, render

_GLYPH = {"info": "info", "warn": "warning", "danger": "error", "ok": "check_circle"}


def callout_html(kind: str, title: str, body: str = "", *, raw_body: bool = False) -> str:
    """kind: info, warn, danger or ok. `body` is escaped unless `raw_body` is set."""
    text = body if raw_body else esc(body)
    head = f"<b>{esc(title)}</b> " if title else ""
    return (
        f'<div class="eis-callout {esc(kind)}" role="note">{icon(_GLYPH.get(kind, "info"), fill=True)}'
        f"<div>{head}{text}</div></div>"
    )


def callout(kind: str, title: str, body: str = "", *, raw_body: bool = False) -> None:
    render(callout_html(kind, title, body, raw_body=raw_body))


def toast(message: str, kind: str = "ok") -> None:
    """A transient confirmation (shown once, then gone)."""
    glyph = {
        "ok": ":material/check_circle:",
        "warn": ":material/warning:",
        "danger": ":material/error:",
    }
    st.toast(message, icon=glyph.get(kind, ":material/info:"))


DATA_CHECK_NOTE = (
    "A data check marks a figure to verify against its filing. It is not a finding that a company "
    "misreported, and it is not a performance ranking: the figure is shown, not placed."
)
STUDY_SAMPLE_NOTE = (
    "Benchmarks are the median, P25 and P75 of the companies in this study sample, not an external "
    "industry benchmark. With about five companies per sector they describe this sample only."
)
POSITION_NOTE = (
    "Colours show position among companies in the same sector. They are not environmental ratings, "
    "ESG scores or a judgement of any company."
)
