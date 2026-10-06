"""Plotly figures shared by the dashboard and the analysis notebook (no interpretation in titles)."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go


def interval_bar(df: pd.DataFrame, x: str, y: str, color: str | None, title: str) -> go.Figure:
    """Bars with asymmetric error bars from the columns `y_lo` and `y_hi`."""
    fig = go.Figure()
    groups = [(None, df)] if color is None else list(df.groupby(color))
    for name, part in groups:
        fig.add_bar(
            x=part[x],
            y=part[y],
            name=None if name is None else str(name),
            error_y={
                "type": "data",
                "symmetric": False,
                "array": (part[y + "_hi"] - part[y]).fillna(0),
                "arrayminus": (part[y] - part[y + "_lo"]).fillna(0),
            },
        )
    fig.update_layout(title=title, barmode="group", yaxis_title=y, margin={"t": 40})
    return fig


def rating_shift_figure(frame: pd.DataFrame) -> go.Figure:
    """Histogram of the T3 rating change C2 minus C1 per model (same model, company, repetition)."""
    ok = frame[frame["valid"]]
    key = ["model_key", "repetition", "company_code"]
    c1 = ok[ok["condition"] == "C1"].set_index(key)["t3_rating"]
    c2 = ok[ok["condition"] == "C2"].set_index(key)["t3_rating"]
    shift = (c2 - c1).dropna().reset_index(name="shift")
    fig = go.Figure()
    for model, part in shift.groupby("model_key"):
        counts = part["shift"].value_counts().sort_index()
        fig.add_bar(x=counts.index.astype(int), y=counts.values, name=model)
    fig.update_layout(
        title="T3 rating change, C2 minus C1",
        barmode="group",
        xaxis_title="rating change",
        yaxis_title="pairs",
        margin={"t": 40},
    )
    return fig


def transition_stack(effects: pd.DataFrame) -> go.Figure:
    """Share of consistent / violating / unconstrained C1 to C2 transitions per model."""
    long = effects.melt(
        id_vars=["model", "role"],
        value_vars=["t3_consistent", "t3_violating", "t3_unconstrained"],
        var_name="label",
        value_name="share",
    )
    fig = go.Figure()
    for label, part in long.groupby("label"):
        fig.add_bar(x=part["model"], y=part["share"], name=label.replace("t3_", ""))
    fig.update_layout(
        title="C1 to C2 transitions by the T3 update rule",
        barmode="stack",
        yaxis_title="share",
        margin={"t": 40},
    )
    return fig


def tercile_figure(position: pd.DataFrame) -> go.Figure:
    """T2 accuracy by third of the prompt (position effect)."""
    part = position[position["outcome"] == "T2 accuracy by tercile"]
    fig = go.Figure()
    for model_set, rows in part.groupby("model_set"):
        rows = rows.sort_values("tercile")
        fig.add_bar(
            x=rows["tercile"].astype(int).astype(str),
            y=rows["value"],
            name=model_set,
            error_y={
                "type": "data",
                "symmetric": False,
                "array": (rows["value_hi"] - rows["value"]).fillna(0),
                "arrayminus": (rows["value"] - rows["value_lo"]).fillna(0),
            },
        )
    fig.update_layout(
        title="T2 accuracy by position in the prompt",
        barmode="group",
        xaxis_title="third of the prompt (1 = first)",
        yaxis_title="T2 accuracy",
        margin={"t": 40},
    )
    return fig


def kpi_trend_figure(history: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for label, part in history.groupby("label"):
        fig.add_scatter(x=part["fy"], y=part["value"], mode="lines+markers", name=label)
    fig.update_layout(title="KPI by fiscal year", margin={"t": 40})
    return fig
