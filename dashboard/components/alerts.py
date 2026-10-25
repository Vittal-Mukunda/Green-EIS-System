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


# Standing notes: said the same way wherever they appear.
ESTIMATE_NOTE = (
    "GreenEIS estimates; it does not certify. Results are a management aid, not an audit and not a "
    "replacement for national inventories."
)
PLACEHOLDER_NOTE = (
    "The trust scores and uncertainty ranges are indicative design values, not calibrated measurements "
    "of error. The study tests them; until it has run on real data, treat the ranges as rough."
)
EXAMPLE_NOTE = (
    "This is an illustrative factory taken from the reference document's worked example. Its numbers are "
    "placeholders, not a real unit. Replace them on the Data entry page."
)
SCOPE_NOTE = (
    "Scope: fuel combustion and purchased electricity. Process emissions and supply-chain (Scope 3) "
    "emissions are not included."
)
