"""Study-sample benchmark cards for the sector pages.

The numbers are the median, P25 and P75 of the companies in this study sample. They are never called
an industry benchmark.
"""

from __future__ import annotations

import pandas as pd

from gauge.viewdata import fmt_number

from .markup import esc
from .status_badge import badge


def benchmark_card_html(
    sector: str,
    summary: pd.DataFrame,
    members: int,
    year: str,
    attention: int,
    selected: bool = False,
) -> str:
    """One sector: how many companies, the year, and each KPI's sample median and P25 to P75."""
    rows = []
    for r in summary.to_dict("records"):
        median = "n/a" if pd.isna(r["median"]) else fmt_number(r["median"])
        spread = (
            "too few to compare"
            if pd.isna(r["p25"])
            else f"{fmt_number(r['p25'])} to {fmt_number(r['p75'])}"
        )
        checks = (
            f' <span class="eis-muted" title="figures failing a data check">({r["data checks"]} data check)</span>'
            if r["data checks"]
            else ""
        )
        rows.append(
            f"<tr><td>{esc(r['label'])}<span class='eis-muted'> · {esc(r['unit'])}</span></td>"
            f"<td><b>{esc(median)}</b></td><td>{esc(spread)}{checks}</td></tr>"
        )
    chip = (
        badge(
            f"{attention} need attention",
            "warn",
            "flag",
            "Companies with a data-check error, or a metric that moved 10% or more the wrong way against the previous year.",
        )
        if attention
        else badge("Nothing needs attention", "ok", "check_circle")
    )
    ring = (
        ' style="border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)"' if selected else ""
    )
    return (
        f'<div class="eis-card"{ring}><div class="eis-bench-head"><div>'
        f'<div class="eis-bench-name">{esc(sector)}</div>'
        f'<div class="eis-bench-meta">{members} companies · {esc(year)}</div></div>{chip}</div>'
        '<table class="eis-bench-table"><thead><tr><th>Metric</th><th>Study-sample median</th>'
        "<th>P25 to P75</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        '<div class="eis-bench-note">Computed from the companies in this sample that pass the data '
        "checks. Not an external industry benchmark.</div></div>"
    )
