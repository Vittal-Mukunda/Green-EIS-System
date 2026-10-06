"""Exception lists and registers: what needs attention, the audit register, the compliance matrix.

A data check is a figure to verify, not a company to blame, so these components say "data check" and
"needs verification" and never rank or score.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from .icons import icon
from .markup import esc
from .status_badge import badge

_TONE = {"warn": "warn", "ok": "ok", "danger": "danger", "info": "info", "na": ""}
_TONE_ICON = {
    "warn": "pending",
    "ok": "check_circle",
    "danger": "error",
    "info": "info",
    "na": "remove_circle",
}


def exceptions_html(items: Sequence[dict]) -> str:
    """The needs-attention panel. Each item: code, who, what, value, unit, why."""
    if not items:
        return ""
    rows = "".join(
        f'<div class="eis-exc"><div><div class="code">{esc(i["code"])}</div>'
        f'<div class="eis-meta">{esc(i["fy"])}</div></div>'
        f'<div><div class="what">{esc(i["who"])} · {esc(i["what"])}</div>'
        f'<div class="why">{esc(i["why"])}</div></div>'
        f'<div class="val">{esc(i["value"])}<small>{esc(i["unit"])}</small>'
        f'<div style="margin-top:4px">{badge("Data check", "warn", "rule")}</div></div></div>'
        for i in items
    )
    return f'<div class="eis-exceptions">{rows}</div>'


def movements_html(items: Sequence[dict]) -> str:
    """Largest year-on-year moves as centred bars. Each item: who, what, change, movement, prev, now, unit."""
    if not items:
        return ""
    biggest = (
        100.0  # bars saturate at 100% so one outlier does not flatten the rest; the label is exact
    )
    rows = []
    for i in items:
        width = min(abs(i["change"]), biggest) / biggest * 50
        side = (
            f"left:50%;width:{width:.1f}%" if i["change"] > 0 else f"right:50%;width:{width:.1f}%"
        )
        way = "better" if i["movement"] == "better" else "worse"
        rows.append(
            f'<div class="eis-move"><div><div class="who">{esc(i["who"])}</div>'
            f'<div class="what">{esc(i["what"])}: {esc(i["prev"])} to {esc(i["now"])} {esc(i["unit"])}</div></div>'
            f'<div class="track" role="img" aria-label="{i["change"]:+.1f} percent"><div class="fill {way}" style="{side}"></div></div>'
            f'<div class="pct">{i["change"]:+.1f}%<div class="eis-meta">{"better" if way == "better" else "worse"}</div></div></div>'
        )
    return f'<div class="eis-moves">{"".join(rows)}</div>'


def register_table_html(rows: pd.DataFrame, name_of) -> str:
    """The audit register: one row per flag with the figure, the issue, the status and the reviewer."""
    if rows.empty:
        return ""
    body = []
    for r in rows.to_dict("records"):
        tone = _TONE.get(r["tone"], "")
        status = f'<span class="eis-badge {tone}">{icon(_TONE_ICON.get(r["tone"], "info"))}{esc(r["status"])}</span>'
        reviewer = (
            esc(r["reviewer"]) if r["reviewer"] else '<span class="eis-na">not yet reviewed</span>'
        )
        when = esc(r["verified_on"]) if r["verified_on"] else '<span class="eis-na">none</span>'
        sev = badge("Error", "danger") if r["severity"] == "error" else badge("Warning", "warn")
        body.append(
            f'<tr><td class="firstcol"><b>{esc(name_of(r["code"]))}</b><span class="sub">{esc(r["sector"])}</span></td>'
            f'<td class="nowrap">{esc(r["fy"])}</td><td>{esc(r["metric"])}</td>'
            f'<td class="num nowrap"><b>{esc(r["reported"])}</b></td>'
            f'<td style="min-width:240px">{esc(r["issue"])}<span class="sub">{esc(r["rule"])}</span></td>'
            f"<td>{sev}</td><td>{status}</td><td>{reviewer}</td><td class='nowrap'>{when}</td></tr>"
        )
    titles = [
        "Company",
        "Fiscal year",
        "Metric",
        "Reported value",
        "Issue",
        "Severity",
        "Status",
        "Reviewer",
        "Verified on",
    ]
    head = f'<th class="firstcol">{titles[0]}</th>' + "".join(f"<th>{h}</th>" for h in titles[1:])
    return (
        '<div class="eis-tablewrap"><table class="eis-table">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def compliance_matrix_html(rows: Sequence[dict], columns: Sequence[str]) -> str:
    """Companies down, checks across. Each row: name, sector, cells (HTML from `status_mark`), passed, of."""
    head = "".join(f"<th>{esc(c)}</th>" for c in columns)
    body = []
    for r in rows:
        cells = "".join(f"<td>{c}</td>" for c in r["cells"])
        body.append(
            f'<tr><td class="firstcol"><b>{esc(r["name"])}</b><span class="sub">{esc(r["sector"])}</span></td>'
            f'{cells}<td class="num nowrap"><b>{r["passed"]}</b> of {r["of"]}</td></tr>'
        )
    return (
        '<div class="eis-tablewrap"><table class="eis-table">'
        f'<thead><tr><th class="firstcol">Company</th>{head}<th>Checks passed</th></tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def rule_summary_html(rows: Sequence[dict]) -> str:
    """Flags by rule: rule, what it checks, errors, warnings."""
    body = "".join(
        f'<tr><td class="firstcol"><span class="eis-mono">{esc(r["rule"])}</span></td><td>{esc(r["what"])}</td>'
        f'<td class="num">{r["error"] or "–"}</td><td class="num">{r["warning"] or "–"}</td></tr>'
        for r in rows
    )
    return (
        '<div class="eis-tablewrap"><table class="eis-table"><thead><tr><th class="firstcol">Rule</th>'
        '<th>What it checks</th><th class="num">Errors</th><th class="num">Warnings</th></tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )
