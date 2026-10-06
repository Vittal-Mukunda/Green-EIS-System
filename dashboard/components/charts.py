"""Plotly in the product's visual language: neutral frame, restrained palette, units on axes.

`show` applies the template and draws the chart. Streamlit's own chart theme is switched off so the
template is what the user sees.
"""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

# Position bands share one blue ramp (see theme.css); the data check is amber, never a rank colour.
BAND_COLOURS = {
    "better third": "#24557a",
    "middle third": "#8aa9c2",
    "weaker third": "#d3dde6",
    "no clear difference": "#cfcdc4",
    "data check": "#e3be68",
    "n/a": "#e5e7eb",
}
SERIES = ["#24557a", "#2e7d5b", "#b7791f", "#8c5a7a", "#5f7f8c", "#9c3a30", "#6b705c", "#4a6fa5"]
FOCUS = "#14532d"
CONTEXT_LINE = "#c4c9c6"
FONT = "Inter, system-ui, -apple-system, 'Segoe UI', sans-serif"

pio.templates["eis"] = go.layout.Template(
    layout={
        "font": {"family": FONT, "size": 12, "color": "#2c3832"},
        "colorway": SERIES,
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "margin": {"l": 56, "r": 16, "t": 28, "b": 44},
        "xaxis": {
            "gridcolor": "#eceae4",
            "linecolor": "#cdcdc4",
            "zerolinecolor": "#cdcdc4",
            "ticks": "outside",
            "tickcolor": "#cdcdc4",
            "title": {"font": {"size": 11.5, "color": "#5d6862"}},
            "tickfont": {"size": 11.5},
        },
        "yaxis": {
            "gridcolor": "#eceae4",
            "linecolor": "#cdcdc4",
            "zerolinecolor": "#cdcdc4",
            "title": {"font": {"size": 11.5, "color": "#5d6862"}},
            "tickfont": {"size": 11.5},
        },
        "legend": {
            "font": {"size": 11.5},
            "bgcolor": "rgba(0,0,0,0)",
            "title": {"font": {"size": 11}},
        },
        "hoverlabel": {
            "font": {"family": FONT, "size": 12},
            "bgcolor": "#1f2a25",
            "font_color": "#fff",
        },
        "title": {"font": {"size": 14}},
    }
)
pio.templates.default = "eis"


def style(fig: go.Figure) -> go.Figure:
    fig.update_layout(template="eis")
    fig.update_xaxes(automargin=True)
    fig.update_yaxes(automargin=True)
    return fig


def show(fig: go.Figure, **kwargs) -> None:
    """Draw a figure with the product template."""
    st.plotly_chart(style(fig), width="stretch", theme=None, **kwargs)
