"""The one-page summary report (ref section 6.9): total emissions with the trust index, the top hotspots,
the cost link, the best scenario found, and a standard method and data-quality note.

The note is always printed. It states what was calculated, from what, and how far to believe it, so the
report cannot be used to overstate performance (ref section 9, "greenwashing").
"""

from __future__ import annotations

from decimal import Decimal

from . import hotspot as hs
from . import recommend as rec
from . import trust as tr
from .engine import GWP_AR5, Activity, calculate
from .factors import FactorLibrary, default_library
from .whatif import Outcome


def _n(value: Decimal | None, places: int = 2) -> str:
    return "n/a" if value is None else f"{value:,.{places}f}"


def _pct(value: Decimal | None, places: int = 1) -> str:
    return "n/a" if value is None else f"{value * 100:.{places}f}%"


def build_report(
    unit_name: str,
    period: str,
    activities: list[Activity],
    cfg: tr.TrustConfig | None = None,
    scenarios: list[Outcome] | None = None,
    library: FactorLibrary | None = None,
) -> str:
    cfg = cfg or tr.TrustConfig()
    library = library or default_library()
    fp = calculate(activities, library)
    total = fp.total_co2e_t
    index = tr.trust_index(fp, cfg)
    u = tr.total_uncertainty(fp, cfg)
    rows = hs.pareto(fp)
    equipment = {a.name: a.equipment for a in activities}

    out: list[str] = [f"# Emissions summary: {unit_name}", f"**Period:** {period}", ""]

    out += ["## Total emissions", ""]
    if u is not None and index is not None:
        out.append(
            f"**{_n(total)} tCO2e**, indicative range {_n(total * (1 - u))} to {_n(total * (1 + u))} "
            f"(plus or minus {_pct(u)}). Data trust index **{_n(index)}** ({tr.band(index, cfg)})."
        )
    else:
        out.append("No emissions were calculated.")
    out.append("")

    out += [
        "## Top hotspots",
        "",
        "| Rank | Activity | tCO2e | Share | Data class |",
        "|---|---|---|---|---|",
    ]
    out += [
        f"| {r.rank} | {r.name} | {_n(r.co2e_t)} | {_pct(r.share)} | {r.data_class} |"
        for r in rows[:3]
    ]
    few = [r.name for r in rows if r.vital_few]
    if few:
        out += ["", f"Together, {', '.join(few)} account for the first 80% of emissions."]
    out.append("")

    if hs.cost_complete(fp):
        out += [
            "## Cost link",
            "",
            "| Activity | Cost (INR) | Cost share | Emission share | INR per tCO2e |",
            "|---|---|---|---|---|",
        ]
        out += [
            f"| {r.name} | {_n(r.cost_inr, 0)} | {_pct(r.cost_share)} | {_pct(r.share)} | "
            f"{_n(r.inr_per_tco2e, 0)} |"
            for r in rows
        ]
        out.append("")
    else:
        out += [
            "## Cost link",
            "",
            "Costs were not entered for every activity, so no cost link is shown.",
            "",
        ]

    out += ["## Best scenario found", ""]
    if scenarios:
        best = max(scenarios, key=lambda o: o.avoided_co2e_t)
        saved = "n/a" if best.cost_saved_inr is None else f"INR {_n(best.cost_saved_inr, 0)}"
        out.append(
            f"{'; '.join(best.titles)}: avoids {_n(best.avoided_co2e_t)} tCO2e "
            f"({_n(best.pct_of_total, 1)}% of the total); energy cost saved {saved}. "
            "Capital cost is not included."
        )
    else:
        out.append("No scenario was run.")
    out.append("")

    recs = rec.recommend(rows, equipment)
    if recs:
        out += ["## Suggestions", ""]
        for r in recs:
            tail = f" Caution: {r.caution}" if r.caution else ""
            out.append(f"- **{r.hotspot}:** {r.action}{tail} (source: {r.sources})")
        out += ["", "These are suggestions drawn from published work, not engineering advice.", ""]

    out += ["## Method and data quality", ""]
    counts = {
        c: sum(1 for a in activities if a.data_class == c)
        for c in ("measured", "estimated", "default")
    }
    out.append(
        f"Inputs: {counts['measured']} measured, {counts['estimated']} estimated, "
        f"{counts['default']} default. Emissions = fuel quantity x net calorific value x emission "
        "factor for CO2, CH4 and N2O, converted to CO2e with "
        f"GWP CH4 = {GWP_AR5['ch4']} and N2O = {GWP_AR5['n2o']}; electricity = kWh x grid factor."
    )
    out.append("")
    out += ["| Item | Factor source | Status |", "|---|---|---|"]
    seen: set[str] = set()
    for r in fp.results:
        if r.factor_id not in seen:
            seen.add(r.factor_id)
            out.append(f"| {r.factor_id} | {r.factor_source} | {r.factor_status} |")
    flags = tr.flag_counts(fp)
    if flags:
        out.append("")
        out += [
            f"- {tr.FLAG_TEXT.get(f, f)} ({n} activit{'y' if n == 1 else 'ies'})"
            for f, n in flags.items()
        ]
    out += [
        "",
        "Scope: fuel combustion and purchased electricity only; process emissions and Scope 3 are excluded.",
    ]
    if cfg.status == "placeholder":
        out.append(
            "The trust scores and uncertainty ranges are indicative design values, not calibrated "
            "measurements of error."
        )
    out += [
        "",
        "**This report estimates emissions; it does not certify them.** It is a management aid, not an "
        "audit or a replacement for national inventories.",
    ]
    return "\n".join(out) + "\n"
