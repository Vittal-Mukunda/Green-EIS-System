from __future__ import annotations

from decimal import Decimal as D

from greeneis import trust, whatif
from greeneis.engine import Activity
from greeneis.report import build_report


def factory(with_cost=True):
    def a(item, qty, unit, cls, cost, label, eq=""):
        return Activity(item, D(qty), unit, cls, D(cost) if with_cost else None, label, eq)

    return [
        a("grid_electricity", "18000", "kWh", "measured", "144000", "Grid electricity"),
        a("coal", "10000", "kg", "estimated", "90000", "Coal (boiler)", "boiler"),
        a("diesel", "2000", "L", "estimated", "180000", "Diesel", "dg_set"),
        a("lpg", "500", "kg", "default", "50000", "LPG (heating)"),
    ]


def test_report_states_the_numbers_the_hand_calculation_gives():
    acts = factory()
    scen = [whatif.run(acts, [whatif.ActivityChange("Diesel", D(15))])]
    text = build_report("Demo unit", "June 2026", acts, scenarios=scen)
    assert "# Emissions summary: Demo unit" in text
    assert "**38.97 tCO2e**" in text
    assert "plus or minus 12.9%" in text
    assert "trust index **0.72** (medium)" in text
    assert "| 1 | Coal (boiler) | 18.91 | 48.5% | estimated |" in text
    assert "avoids 0.82 tCO2e" in text and "INR 27,000" in text
    assert "4,759" in text  # coal INR per tCO2e


def test_report_always_carries_the_method_note_and_the_no_certification_line():
    text = build_report("X", "m", factory(with_cost=False))
    assert "does not certify" in text
    assert "indicative design values" in text
    assert "Costs were not entered" in text
    assert "No scenario was run." in text
    assert "CSTEP 2018" in text and "CEA CO2 Baseline Database" in text
    assert "coal grade is unknown" in text.lower()


def test_calibrated_config_drops_the_placeholder_sentence():
    cfg = trust.TrustConfig(status="calibrated")
    assert "indicative design values" not in build_report("X", "m", factory(), cfg=cfg)


def test_empty_unit_does_not_crash():
    assert "No emissions were calculated." in build_report("X", "m", [])
