"""The plain-language layer: a short reading under a chart or table, and the ways numbers are said.

A reading says what the figure means for someone who has not seen the study, in one or two sentences,
and a second line says how to read the chart itself. The numbers in a reading come from the caller; this
module only words them.
"""

from __future__ import annotations

import streamlit as st

from .alerts import callout


def in_plain_words(text: str, read: str = "") -> None:
    """A reading of the figure above it, with an optional line on how to read the chart."""
    callout("info", "In plain words.", text)
    if read:
        st.caption(f"How to read this: {read}")


def pct(fraction: float, places: int = 0) -> str:
    """0.0625 becomes '6%'. Large errors keep their thousands separator: 5.99 becomes '599%'."""
    return f"{fraction * 100:,.{places}f}%"


def one_in(fraction: float) -> str:
    """'one in ten' for 0.10, 'about one in four' for 0.26. Used for tails, never for precision."""
    if fraction <= 0:
        return "none"
    words = {2: "two", 3: "three", 4: "four", 5: "five", 10: "ten", 20: "twenty"}
    n = round(1 / fraction)
    return f"about one in {words.get(n, str(n))}"
