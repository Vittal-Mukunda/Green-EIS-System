"""The Study results page: what the study harness found, with its provenance on the page.

It reads the JSON files written by `python -m greeneis.study.run` from `outputs/`. It never runs the study
and never shows a result without saying where the data came from.
"""

from __future__ import annotations

import json
from pathlib import Path

import state
import streamlit as st
from components.alerts import callout
from components.data_table import Column, Html, table_html
from components.empty_state import empty_state
from components.kpi_card import stat_strip
from components.markup import render, section
from components.page_header import page_header
from components.status_badge import badge

OUTPUTS = Path(__file__).resolve().parents[1] / "outputs"

VERDICT_TONE = {"supported": "ok", "not supported": "warn", "insufficient data": ""}

PLAIN = {
    "H1": "Default inputs are further from the truth than Estimated inputs.",
    "H2": "The placeholder uncertainty ranges do not match the errors actually seen.",
    "H3": "A higher trust index goes with a smaller error in the total.",
    "H4": "The largest hotspot is usually still the largest when the data are degraded, less so when its lead is thin.",
    "H5": "Improving the data of the largest hotspot first reduces error more than the alternatives.",
}


def _fmt(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    if isinstance(value, list):
        return "[" + ", ".join(_fmt(v) for v in value) + "]"
    if isinstance(value, dict):
        return "; ".join(f"{k}: {_fmt(v)}" for k, v in value.items())
    return str(value)


def study_results(ctx: state.Context) -> None:
    page_header(
        "Study results",
        "Whether the trust score and the hotspot logic hold up when real inputs are replaced by what a unit "
        "without records would derive. This tests the system; it says nothing about any one unit.",
        compared="Five pre-specified hypotheses, H1 to H5, each stated as something that could be proved wrong.",
        read="'Supported' means the condition for proving the hypothesis wrong was rejected after correcting for "
        "five tests. 'Not supported' is not the same as refuted. 'Insufficient data' means too few clusters or rows.",
    )
    # Main runs first (newest first), sensitivity and exploratory runs after them.
    files = sorted(
        OUTPUTS.glob("study*.json"),
        key=lambda f: ("_sens_" in f.name or "_explor_" in f.name, -f.stat().st_mtime),
    )
    if not files:
        empty_state(
            "No study result yet",
            "Run the study to create one. It needs a case table of real data (see docs/ASI_OPTION.md).",
            "science",
        )
        st.code(
            'python -m greeneis.study.run --source csv --path cases.csv --reference "reported to the government" --out outputs/study_real.json',
            language="bash",
        )
        return
    choice = st.selectbox("Result file", [f.name for f in files], key="study_file")
    result = json.loads((OUTPUTS / choice).read_text(encoding="utf-8"))
    prov = result["provenance"]
    if prov["synthetic"]:
        callout("danger", "Synthetic data.", prov["banner"])
    stat_strip(
        [
            ("Data source", prov["source"], "synthetic" if prov["synthetic"] else "not synthetic"),
            ("Units", f"{prov['units']:,}", f"{prov['rows']:,} item records"),
            ("Clusters", f"{prov['clusters']:,}", "the bootstrap resamples these"),
            (
                "Reference quantity",
                prov["reference_quantity"][:28],
                prov["reference_quantity"][28:] or "what the errors are measured against",
            ),
        ]
    )
    if prov["trust_config"]["status"] == "placeholder":
        st.caption("Scores and uncertainty ranges tested here are the uncalibrated placeholders.")

    section("Hypotheses", "Holm-adjusted across the five")
    rows = []
    for name, t in result["tests"].items():
        p = t["adjusted_p"]
        rows.append(
            [
                name,
                PLAIN.get(name, t["statement"]),
                Html(badge(t["verdict"].capitalize(), VERDICT_TONE.get(t["verdict"], ""))),
                f"{p:.4f}" if p is not None else None,
                f"{t['n_rows']:,}",
                f"{t['n_clusters']:,}",
            ]
        )
    render(
        table_html(
            [
                Column("H"),
                Column("In plain words"),
                Column("Verdict"),
                Column("Adjusted p", numeric=True),
                Column("Rows", numeric=True),
                Column("Clusters", numeric=True),
            ],
            rows,
        )
    )
    st.caption(
        "A verdict that rests on few rows is weak even when it says Supported: compare the Rows column. "
        "Pooled results are dominated by the item with the most records. "
        "What each result does and does not show is written up in docs/RESULTS_ASI_2023-24.md."
    )
    for name, t in result["tests"].items():
        with st.expander(f"{name} detail: {t['statement']}"):
            if not t["estimate"]:
                st.write("Not enough data to estimate.")
            for k, v in t["estimate"].items():
                st.markdown(f"- **{k.replace('_', ' ')}:** {_fmt(v)}")
            if t.get("note"):
                st.caption(t["note"])

    by_item = result["descriptives"].get("item_errors_by_item", {})
    if by_item:
        section(
            "Error of each proxy, by fuel",
            "Absolute relative error; the pooled figures are dominated by the biggest item",
        )
        render(
            table_html(
                [
                    Column("Item"),
                    Column("Records", numeric=True),
                    Column("Estimated: median", numeric=True),
                    Column("Estimated: 90th percentile", numeric=True),
                    Column("Default: median", numeric=True),
                    Column("Default: 90th percentile", numeric=True),
                ],
                [
                    [
                        item,
                        f"{d['eps_estimated']['n']:,}",
                        f"{d['eps_estimated']['median_abs'] * 100:.0f}%",
                        f"{d['eps_estimated']['q90_abs'] * 100:.0f}%",
                        f"{d['eps_default']['median_abs'] * 100:.0f}%",
                        f"{d['eps_default']['q90_abs'] * 100:,.0f}%",
                    ]
                    for item, d in sorted(
                        by_item.items(), key=lambda kv: -kv[1]["eps_estimated"]["n"]
                    )
                ],
            )
        )

    desc = result["descriptives"].get("by_profile", {})
    if desc:
        section(
            "By data-quality profile",
            "A profile is an assumption about what a unit keeps records of",
        )
        render(
            table_html(
                [
                    Column("Profile"),
                    Column("Units", numeric=True),
                    Column("Median total error", numeric=True),
                    Column("Mean trust index", numeric=True),
                    Column("Range covers truth", numeric=True),
                    Column("Top hotspot kept", numeric=True),
                ],
                [
                    [
                        name,
                        f"{d['units']:,}",
                        f"{d['median_abs_total_error'] * 100:.1f}%",
                        f"{d['mean_trust_index']:.2f}",
                        f"{d['coverage'] * 100:.0f}%",
                        f"{d['top1_kept'] * 100:.0f}%"
                        if d["top1_kept"] == d["top1_kept"]
                        else None,
                    ]
                    for name, d in desc.items()
                ],
            )
        )
    if result["descriptives"].get("excluded"):
        st.caption(
            "Left out because a proxy could not be formed: "
            + "; ".join(f"{k} ({v} units)" for k, v in result["descriptives"]["excluded"].items())
        )
