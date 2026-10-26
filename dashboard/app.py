"""GreenEIS dashboard. Run with `streamlit run dashboard/app.py`.

The navigation is the research story: Study, one analysis page per research gap, Overall Findings,
References. The gaps come from `greeneis.gaps`, so the sidebar, the Study page and the findings table are
generated from one list. Each page has its own address: `?page=gap-1-firm-level-data`.

Pages read the result files in `outputs/` and the factor library; nothing is computed here and nothing is
entered by the visitor. The earlier unit tool (data entry, summary, hotspots, what-if, report) is not in
this navigation; it still runs from `dashboard/legacy_app.py`.
"""

from __future__ import annotations

import sys
from functools import partial
from pathlib import Path

# A host that only runs `pip install -r requirements.txt` has not installed this project, so put `src/`
# (and this folder, for the page modules) on the path before importing.
for _path in (Path(__file__).resolve().parents[1] / "src", Path(__file__).resolve().parent):
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import gap_data  # noqa: E402
import pages_bibliography  # noqa: E402
import pages_findings  # noqa: E402
import pages_gap  # noqa: E402
import streamlit as st  # noqa: E402
import vocab  # noqa: E402
from components.alerts import ESTIMATE_NOTE  # noqa: E402
from components.app_shell import inject_styles, render_shell  # noqa: E402
from components.navigation import scroll_to_top_if_requested  # noqa: E402

from greeneis import gaps  # noqa: E402

st.set_page_config(
    page_title="GreenEIS",
    page_icon=":material/eco:",
    layout="wide",
    initial_sidebar_state="auto",  # open on a laptop, collapsed on a phone
)

PAGES = list(vocab.PAGES)
PAGE_FUNCTIONS = {
    "Study": pages_gap.study,
    **{g.nav_label: partial(pages_gap.analysis, g.number) for g in gaps.GAPS},
    "Overall Findings": pages_findings.overall_findings,
    "References": pages_bibliography.bibliography,
}
assert list(PAGE_FUNCTIONS) == PAGES, "every navigation page needs a function, in sidebar order"

# A page's address picks the page on first load, so a link such as ?page=overall-findings can be shared.
if st.session_state.get("view") not in PAGES:
    slugs = {vocab.slug(v): v for v in PAGES}
    st.session_state["view"] = slugs.get(st.query_params.get("page", ""), PAGES[0])

inject_styles(PAGES)

head = gap_data.result(gap_data.MAIN_FILE)
status = (
    (f"Real data: ASI 2023-24 · {head.factories:,} small factories · aggregates only", "")
    if head
    else ("Real results file not available", "warn")
)
page = render_shell(PAGES, None, status[0], status[1])
st.query_params["page"] = vocab.slug(page)

PAGE_FUNCTIONS[page]()
st.caption(ESTIMATE_NOTE)
scroll_to_top_if_requested()
