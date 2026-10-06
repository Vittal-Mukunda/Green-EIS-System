"""Filter and paging controls shared by the pages."""

from __future__ import annotations

import math

import pandas as pd
import streamlit as st


def year_picker(analysis_fy: str, years: list[str], key: str, label: str = "Fiscal year") -> str:
    """Fiscal-year select, opening on the analysis year (or the latest loaded)."""
    start = years.index(analysis_fy) if analysis_fy in years else len(years) - 1
    return st.selectbox(label, years, index=start, key=key)


def paginate(frame: pd.DataFrame, page_size: int, key: str) -> pd.DataFrame:
    """Show `page_size` rows at a time with previous / next controls. The page resets when the number of
    rows changes (a filter was applied), so the user is never left on a page that no longer exists."""
    total = len(frame)
    pages = max(1, math.ceil(total / page_size))
    sig_key, page_key = f"{key}_sig", f"{key}_page"
    if st.session_state.get(sig_key) != total:
        st.session_state[sig_key] = total
        st.session_state[page_key] = 1
    page = min(max(int(st.session_state.get(page_key, 1)), 1), pages)
    st.session_state[page_key] = page
    if pages > 1:
        left, middle, right = st.columns([1, 3, 1], vertical_alignment="center")
        if left.button(
            "Previous", key=f"{key}_prev", disabled=page <= 1, icon=":material/chevron_left:"
        ):
            st.session_state[page_key] = page - 1
            st.rerun()
        first, last = (page - 1) * page_size + 1, min(page * page_size, total)
        with middle:
            st.html(
                "<div style='text-align:center;font-size:12.5px;color:#5d6862'>"
                f"Rows {first} to {last} of {total} · page {page} of {pages}</div>"
            )
        if right.button(
            "Next", key=f"{key}_next", disabled=page >= pages, icon=":material/chevron_right:"
        ):
            st.session_state[page_key] = page + 1
            st.rerun()
    return frame.iloc[(page - 1) * page_size : page * page_size]
