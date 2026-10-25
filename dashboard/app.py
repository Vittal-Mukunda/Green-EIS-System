"""GreenEIS dashboard. Run with `streamlit run dashboard/app.py`.

Each page has its own address: `?page=hotspots`. The pages call components and the `greeneis` package;
the numbers are never computed here. Nothing is stored on disk: the data a person enters live in the
browser session, and the Data entry page offers a CSV to keep them.
"""

from __future__ import annotations

import sys
from pathlib import Path

# A host that only runs `pip install -r requirements.txt` has not installed this project, so put `src/`
# (and this folder, for the page modules) on the path before importing.
for _path in (Path(__file__).resolve().parents[1] / "src", Path(__file__).resolve().parent):
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pages_reference  # noqa: E402
import pages_study  # noqa: E402
import pages_unit  # noqa: E402
import state  # noqa: E402
import streamlit as st  # noqa: E402
import vocab  # noqa: E402
from components.alerts import ESTIMATE_NOTE  # noqa: E402
from components.app_shell import inject_styles, render_shell  # noqa: E402

st.set_page_config(
    page_title="GreenEIS",
    page_icon=":material/eco:",
    layout="wide",
    initial_sidebar_state="auto",  # open on a laptop, collapsed on a phone
)

PAGES = list(vocab.PAGES)
PAGE_FUNCTIONS = {
    "Data entry": pages_unit.data_entry,
    "Summary": pages_unit.summary,
    "Hotspots": pages_unit.hotspots,
    "What-if": pages_unit.what_if,
    "Report": pages_unit.report,
    "Study results": pages_study.study_results,
    "Factors and method": pages_reference.factors_and_method,
    "About": pages_reference.about,
}

state.init_state()
# A page's address picks the page on first load, so a link such as ?page=hotspots can be shared.
if st.session_state.get("view") not in PAGES:
    slugs = {vocab.slug(v): v for v in PAGES}
    st.session_state["view"] = slugs.get(st.query_params.get("page", ""), PAGES[0])

inject_styles(PAGES)
ctx = state.build_context()


def _scope_control() -> None:
    """Choose one period or all of them; shown only when more than one period has been entered."""
    if len(st.session_state["periods"]) > 1:
        st.radio("Show", ["This period", "All periods entered"], key="scope")


unit_block = {
    "name": ctx.unit_name,
    "period": ctx.period,
    "activities": len(ctx.activities),
    "is_example": ctx.is_example,
}
status = (
    ("Illustrative example, not real data", "warn")
    if ctx.is_example
    else (f"{ctx.unit_name} · {ctx.period} · {len(ctx.activities)} activities", "")
)
page = render_shell(PAGES, unit_block, status[0], status[1], extra=_scope_control)
st.query_params["page"] = vocab.slug(page)

PAGE_FUNCTIONS[page](ctx)
st.caption(ESTIMATE_NOTE)
