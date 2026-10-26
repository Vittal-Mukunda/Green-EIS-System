"""The analysis page for one research gap, and the Study page that introduces all of them.

Every analysis page has the same eight parts, A to H, so an evaluator can compare gaps like for like:
research question, academic context, data and scope, methodology, real-data results, findings,
contribution to the gap, limitations and reproducibility. The parts that depend on the question are in
`gap_content`; this module is the shared frame and reads gap titles, sources and statuses from
`greeneis.gaps`, so the Study page, the analysis pages and Overall Findings cannot disagree.
"""

from __future__ import annotations

import findings
import gap_content
import gap_data
import streamlit as st
import vocab
from components.citations import origin_detail_html, source_table_html
from components.markup import render, section
from components.navigation import primary_button
from components.page_header import page_header
from components.research import gap_head, qa, qa_html, status_badge
from components.status_badge import badge

from greeneis import gaps

COMMANDS = {
    "study": (
        "python -m greeneis.study.run --source asi --path C:/Users/vitta/greeneis-data/asi/ASI24m.TXT "
        "--seed 20261025 --boot 1000 --out outputs/study_asi_2023-24.json"
    ),
    "evidence": (
        "python -m greeneis.study.gap_evidence --path C:/Users/vitta/greeneis-data/asi/ASI24m.TXT"
    ),
}
# Which result files and commands each gap's numbers come from.
DEPENDS = {
    1: (("study", gap_data.MAIN_FILE), ("evidence", gap_data.EVIDENCE_FILE)),
    2: (("study", gap_data.MAIN_FILE), ("study", gap_data.TEXTILE_FILE)),
    3: (("study", gap_data.MAIN_FILE), ("evidence", gap_data.EVIDENCE_FILE)),
    4: (("evidence", gap_data.EVIDENCE_FILE),),
    5: (),
    6: (),
    7: (),
}

ATTRIBUTION_TONE = {"verified": "ok", "interpretation": "info", "unverified": "warn"}


def _status_row(gap: gaps.Gap) -> str:
    return (
        status_badge(gap.status, gap.status_text)
        + " "
        + badge(
            gaps.ATTRIBUTION_LEVELS[gap.attribution].split(":")[0],
            ATTRIBUTION_TONE[gap.attribution],
        )
    )


# ---- Study page ----------------------------------------------------------------------------------
def study() -> None:
    page_header("Study", page="Study")
    for g in gaps.GAPS:
        _study_section(g)


def _study_section(g: gaps.Gap) -> None:
    summary = findings.summary(g.number)
    with st.container(border=True):
        gap_head(f"Gap {g.id[1:]}: {g.title}", _status_row(g))
        origin, cites = origin_detail_html(g)
        render(qa_html("Originating study", origin, raw=True))
        render(qa_html("Citation", cites, raw=True))
        render(
            qa_html(
                "Attribution", f"{gaps.ATTRIBUTION_LEVELS[g.attribution]}. {g.attribution_note}"
            )
        )
        qa("What did the study investigate?", g.studied)
        qa("What did the study find?", g.found)
        qa("What is the research gap, in very simple words?", g.gap_simple)
        qa("The gap, more precisely", g.gap_academic)
        qa("Why does the gap matter?", g.why_matters)
        qa("What does GreenEIS do?", g.greeneis_does)
        qa("Evidence available in this project", g.evidence + " " + summary.key_finding)
        qa("Analysis status", f"{g.status_text}. {g.status_reason}")
        primary_button("Explore this analysis →", g.nav_label, f"study_{g.slug}", list(vocab.PAGES))


# ---- Analysis page -------------------------------------------------------------------------------
def analysis(number: int) -> None:
    g = gaps.get(number)
    content = gap_content.CONTENT[number]
    summary = findings.summary(number)
    f = content.findings()
    page_header(
        f"Gap {number}. {g.title}",
        f"The real-data analysis for research gap {number}: {g.question}",
        compared=f.comparisons,
        read="Parts A to H are the same on every gap page. Numbers are read from the result files and "
        "are not typed in; where the data cannot answer the question, the page says so.",
        page=g.nav_label,
    )
    render(_status_row(g))

    section("A. Research question")
    qa("The question", g.question)
    qa(
        "How it relates to the gap",
        f"This tests the gap: {g.title}. The Study page sets out where the gap comes from.",
    )
    primary_button(
        "Back to this gap on the Study page", "Study", f"back_{g.slug}", list(vocab.PAGES)
    )

    section("B. Academic context")
    render(source_table_html(g.sources))
    qa("The limitation that motivates the analysis", g.gap_academic)
    render(
        qa_html("Attribution", f"{gaps.ATTRIBUTION_LEVELS[g.attribution]}. {g.attribution_note}")
    )

    section("C. Data and scope")
    content.scope()

    section("D. Methodology")
    content.method()

    section("E. Real-data results", f"Reporting period: {gap_content.PERIOD}")
    content.results()

    section("F. Findings and interpretation")
    qa("What the data shows", f.shows)
    render(qa_html("The most important numbers", f.numbers))
    qa("Which comparisons matter", f.comparisons)
    qa("Can the research question be answered?", f.answerable)
    has_origin = any(s.role == "originating" for s in g.sources)
    render(
        qa_html(
            "How this relates to the originating paper"
            if has_origin
            else "How this relates to the closest sources (no originating paper verified)",
            f.relation,
            raw=True,
        )
    )
    qa("What the evidence cannot establish", f.cannot)
    st.caption(
        "These are descriptive findings. Nothing here is a causal claim, and 'supported' for a "
        "hypothesis means its pre-specified falsification condition was rejected."
    )

    section("G. Contribution to the research gap")
    render(status_badge(g.status, g.status_text))
    qa("Why this status", g.status_reason)
    st.caption(
        "A built feature does not by itself resolve a gap: the status follows the strength of the evidence."
    )

    section("H. Limitations and reproducibility")
    st.markdown("**Limitations**\n" + "\n".join(f"- {x}" for x in g.limits))
    qa("Data that would close or test the gap", g.missing)
    needs = DEPENDS[number]
    if needs:
        st.markdown("**Reproduce the numbers on this page**")
        for kind in dict.fromkeys(k for k, _ in needs):
            st.code(COMMANDS[kind], language="bash")
        st.caption(
            "The ASI file is kept outside the project and its portal terms are unread (V-18), so only "
            "aggregate results are stored and shown."
        )
        for _kind, name in dict.fromkeys(needs):
            path = gap_data.source_file(name)
            if path is not None:
                st.download_button(
                    f"Download {name}",
                    path.read_bytes(),
                    file_name=name,
                    mime="application/json",
                    key=f"dl_{g.slug}_{name}",
                )
    else:
        st.caption(
            "This page uses the published factors and the code in `src/greeneis`; there is no result "
            "file to download. The factor tables are in `src/greeneis/data/`."
        )
    st.caption(f"Summary used on the Overall Findings page: {summary.key_finding}")
