"""The Factors and method page, and the About page."""

from __future__ import annotations

import state
import streamlit as st
from components.alerts import ESTIMATE_NOTE, PLACEHOLDER_NOTE, SCOPE_NOTE, callout
from components.data_table import Column, Html, table_html
from components.markup import render, section
from components.page_header import page_header
from components.status_badge import badge

from greeneis.engine import GWP_AR5
from greeneis.factors import default_library
from greeneis.trust import PLACEHOLDER_SCORES, PLACEHOLDER_UNCERTAINTY

STATUS_TONE = {
    "source_verified": "ok",
    "derived_reading": "info",
    "assumed": "warn",
    "unverified": "warn",
}
STATUS_TEXT = {
    "source_verified": "Verified in source",
    "derived_reading": "Needs interpretation",
    "assumed": "Assumed",
    "unverified": "Unverified",
}

LIMITATIONS = [
    (
        "Self-reported data may be wrong or incomplete",
        "Every number carries a data class and the trust index shows how much rests on estimates.",
    ),
    (
        "Default factors are national averages",
        "Coal grade is unknown in most small units, so one coal factor is used and flagged.",
    ),
    (
        "The trust scores are not calibrated",
        "They are placeholders. The study tests them; report them as indicative.",
    ),
    (
        "Scope is fuel and electricity only",
        "Process emissions and supply-chain emissions are not included.",
    ),
    (
        "The grid factor changes each year",
        "The factor is version-stamped; check the current CEA release before real use.",
    ),
    (
        "Recommendations may not fit local conditions",
        "They are drawn from cluster-level studies and shown with cautions.",
    ),
    (
        "Possible misuse as a green label",
        "The report always prints the method, data classes and trust index.",
    ),
]


def factors_and_method(ctx: state.Context) -> None:
    page_header(
        "Factors and method",
        "Every emission factor with its source and year, the formulas, and the trust classes.",
        read="A factor marked 'Verified in source' was read in the document named. Others say what is still open.",
    )
    lib = default_library()
    section("Calculation")
    st.latex(
        r"E_{\text{fuel}}\,(\mathrm{TJ}) = Q\,(\mathrm{kt}) \times \mathrm{NCV}\,(\mathrm{TJ/kt})"
    )
    st.latex(
        r"\mathrm{CO_2e}\,(\mathrm{t}) = \mathrm{CO_2} + 28\times\mathrm{CH_4} + 265\times\mathrm{N_2O}"
    )
    st.latex(
        r"\mathrm{CO_2e}_{\text{electricity}}\,(\mathrm{t}) = \text{MWh} \times \text{grid factor}\,(\mathrm{tCO_2/MWh})"
    )
    st.caption(
        f"Each gas = energy times its factor (kg per TJ) divided by 1000. Warming potentials CH4 = {GWP_AR5['ch4']}, N2O = {GWP_AR5['n2o']} (100-year, as used by CSTEP)."
    )

    section("Fuel factors", "kg per TJ; NCV in TJ per kt")
    render(
        table_html(
            [
                Column("Fuel"),
                Column("NCV", numeric=True, note="TJ/kt"),
                Column("CO2", numeric=True, note="kg/TJ"),
                Column("CH4", numeric=True, note="kg/TJ"),
                Column("N2O", numeric=True, note="kg/TJ"),
                Column("Source"),
                Column("Status"),
            ],
            [
                [
                    f.name,
                    f"{f.ncv_tj_per_kt:g}",
                    f"{f.ef_co2_kg_per_tj:,.0f}",
                    f"{f.ef_ch4_kg_per_tj:g}",
                    f"{f.ef_n2o_kg_per_tj:g}",
                    f"{f.source} ({f.source_year})",
                    Html(badge(STATUS_TEXT[f.status], STATUS_TONE[f.status], tip=f.note)),
                ]
                for f in lib.fuels
            ],
        )
    )
    section("Grid electricity", "tCO2 per MWh, CO2 only")
    render(
        table_html(
            [
                Column("Factor"),
                Column("Value", numeric=True),
                Column("Boundary"),
                Column("Source"),
                Column("Status"),
            ],
            [
                [
                    g.name,
                    f"{g.ef_t_co2_per_mwh}",
                    g.boundary,
                    f"{g.source} ({g.source_year})",
                    Html(badge(STATUS_TEXT[g.status], STATUS_TONE[g.status], tip=g.note)),
                ]
                for g in lib.grids
            ],
        )
    )
    st.caption(
        "Fuels not yet in the library (pet coke, wood, biomass) are not available until an Indian source is verified."
    )

    section("Trust classes", "Placeholders, not findings")
    render(
        table_html(
            [
                Column("Class"),
                Column("Score", numeric=True),
                Column("Indicative range", numeric=True),
            ],
            [
                [
                    c.capitalize(),
                    f"{PLACEHOLDER_SCORES[c]}",
                    f"plus or minus {float(PLACEHOLDER_UNCERTAINTY[c]) * 100:.0f}%",
                ]
                for c in ("measured", "estimated", "default")
            ],
        )
    )
    st.latex(
        r"T=\frac{\sum_i E_i s_i}{\sum_i E_i}\qquad U=\frac{\sqrt{\sum_i (E_i u_i)^2}}{\sum_i E_i}"
    )
    st.caption(
        PLACEHOLDER_NOTE
        + " The root-sum-square assumes independent errors, which is optimistic when one proxy feeds several inputs."
    )

    section("Limitations")
    render(table_html([Column("Limitation"), Column("How it is handled")], LIMITATIONS))


def about(ctx: state.Context) -> None:
    page_header("About", "What this system is, what it is not, and the state it is in.")
    st.markdown(
        """
GreenEIS turns a small manufacturing unit's monthly energy, fuel and cost data into emissions, a trust score
for every number, hotspots, a cost link and what-if scenarios.

**Why.** National estimates of emissions from India's informal manufacturing sector are built from fuel-supply
or survey data and differ from each other; both research groups that produced them ask for firm-level fuel data.
GreenEIS is a way for a unit to record its own, and to see how far to believe it.

**What the research tests.** Whether the Measured / Estimated / Default label actually predicts the error in a
unit's footprint and the stability of its hotspot ranking (the Study results page).
"""
    )
    callout("warn", "What it is not.", ESTIMATE_NOTE)
    callout("info", "Scope.", SCOPE_NOTE)
    section("State of the project")
    st.markdown(
        """
- The calculation engine reproduces published arithmetic (CSTEP 2018) and flags, rather than corrects, cells
  where the report disagrees with its own factors.
- The trust scores are placeholders. The study that tests them has been run once on real data, the ASI
  2023-24 factory returns (reported, not metered; registered factories, not informal units; one year). It
  shows the placeholder ranges are wrong, and wrong differently for each fuel. See Trust in numbers.
- No real unit-level energy audit has been obtained. The usability check and the buyer review are
  written but not run.
- Data entered here stay in this browser session; download them as a CSV to keep them.
"""
    )
