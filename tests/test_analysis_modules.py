"""Trust score, hotspots, cost link, what-if and recommendations on the reference document's illustrative
factory (ref section 7). Expected values were worked out by hand; per-activity CO2e (t):

    grid 13.086 (measured) | coal 18.91155 (estimated) | diesel 5.47238823 (estimated)
    LPG 1.496252725 (default)           total 38.966190955

    T = (13.086 + 0.6 x 18.91155 + 0.6 x 5.47238823 + 0.3 x 1.496252725) / total
      = 28.1652387555 / 38.966190955 = 0.7228122
    U = sqrt(0.6543^2 + 4.7278875^2 + 1.3680970575^2 + 0.7481263625^2) / total
      = sqrt(25.2124113) / 38.9661910 = 5.02119 / 38.96619 = 0.1288603
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from greeneis import hotspot, recommend, trust, whatif
from greeneis.engine import Activity, calculate


def act(item, qty, unit, cls, cost, label, equipment=""):
    return Activity(
        item_id=item,
        quantity=D(qty),
        unit=unit,
        data_class=cls,
        cost_inr=D(cost) if cost is not None else None,
        label=label,
        equipment=equipment,
    )


def factory(with_cost=True):
    c = (lambda x: x) if with_cost else (lambda x: None)
    return [
        act("grid_electricity", "18000", "kWh", "measured", c("144000"), "Grid electricity"),
        act("coal", "10000", "kg", "estimated", c("90000"), "Coal (boiler)", "boiler"),
        act("diesel", "2000", "L", "estimated", c("180000"), "Diesel", "dg_set"),
        act("lpg", "500", "kg", "default", c("50000"), "LPG (heating)"),
    ]


def close(value, expected, places="1e-6"):
    return abs(value - D(expected)) < D(places)


# ---- trust ---------------------------------------------------------------------------------
def test_trust_index_and_uncertainty_match_the_hand_calculation():
    fp = calculate(factory())
    assert close(trust.trust_index(fp), "0.7228122")
    assert close(trust.total_uncertainty(fp), "0.1288603")
    assert trust.band(trust.trust_index(fp)) == "medium"
    lo, hi = trust.interval(fp)
    assert close(lo, "33.944995", "1e-5") and close(hi, "43.987387", "1e-5")


def test_uncertainty_is_dominated_by_the_estimated_coal():
    fp = calculate(factory())
    shares = trust.variance_contributions(fp)
    # coal's squared term 22.3577... / 25.2124... = 0.8866 (hand calculation above)
    assert close(shares[1], "0.88658", "1e-4")
    assert max(shares, key=shares.get) == 1
    assert close(sum(shares.values()), "1")


def test_everything_measured_gives_index_one():
    acts = [a.__class__(**{**a.__dict__, "data_class": "measured"}) for a in factory()]
    fp = calculate(acts)
    assert trust.trust_index(fp) == D(1)
    # root-sum-square of independent 5% terms: 0.05 x sqrt(sum E^2) / sum E. By hand, sum E^2 =
    # 171.2434 + 357.6467 + 29.9474 + 2.2388 = 561.0763, sqrt = 23.6871, / 38.9662 = 0.60789, x 0.05
    assert close(trust.total_uncertainty(fp), "0.0303944", "1e-6")


def test_bands_and_empty_footprint():
    assert trust.band(D("0.8")) == "high" and trust.band(D("0.5")) == "medium"
    assert trust.band(D("0.49")) == "low" and trust.band(None) == "not available"
    empty = calculate([])
    assert trust.trust_index(empty) is None and trust.total_uncertainty(empty) is None


def test_config_must_cover_the_three_classes():
    with pytest.raises(ValueError):
        trust.TrustConfig(scores={"measured": D(1)})
    cfg = trust.TrustConfig(scores={"measured": D(1), "estimated": D("0.5"), "default": D("0.1")})
    assert trust.trust_index(calculate(factory()), cfg) < trust.trust_index(calculate(factory()))


def test_flags_are_counted():
    counts = trust.flag_counts(calculate(factory()))
    assert counts["coal_grade_assumed"] == 1 and counts["assumed_density"] == 1


# ---- hotspots and cost link ----------------------------------------------------------------
def test_pareto_order_shares_and_vital_few():
    rows = hotspot.pareto(calculate(factory()))
    assert [r.name for r in rows] == [
        "Coal (boiler)",
        "Grid electricity",
        "Diesel",
        "LPG (heating)",
    ]
    assert close(rows[0].share, "0.4853323", "1e-6") and close(rows[1].share, "0.3358296", "1e-6")
    assert close(rows[1].cumulative_share, "0.8211619", "1e-6")  # 0.4853323 + 0.3358296
    assert [r.vital_few for r in rows] == [True, True, False, False]  # the 2nd one reaches 80%
    assert close(rows[-1].cumulative_share, "1")


def test_cost_link_matches_the_reference_table():
    rows = {r.name: r for r in hotspot.pareto(calculate(factory()))}
    assert close(rows["Coal (boiler)"].inr_per_tco2e, "4759", "1")
    assert close(rows["Grid electricity"].inr_per_tco2e, "11004", "1")
    assert close(rows["Diesel"].inr_per_tco2e, "32892", "1")
    assert close(rows["LPG (heating)"].inr_per_tco2e, "33417", "1")
    assert close(rows["Diesel"].cost_share, "0.3879310", "1e-6")  # 180,000 / 464,000
    assert rows["Coal (boiler)"].reading == hotspot.READING["emissions"]
    assert rows["Grid electricity"].reading == hotspot.READING["both"]
    assert rows["Diesel"].reading == hotspot.READING["cost"]
    assert rows["LPG (heating)"].reading == hotspot.READING["minor"]


def test_missing_costs_give_no_cost_columns():
    fp = calculate(factory(with_cost=False))
    assert not hotspot.cost_complete(fp)
    rows = hotspot.pareto(fp)
    assert all(r.cost_share is None and r.inr_per_tco2e is None and r.reading == "" for r in rows)


# ---- what-if -------------------------------------------------------------------------------
def test_reference_scenarios_a_b_c_and_combined():
    acts = factory()
    a = whatif.run(acts, [whatif.ActivityChange("Diesel", D(15))])
    b = whatif.run(acts, [whatif.ActivityChange("Coal (boiler)", D(10))])
    c = whatif.run(acts, [whatif.ElectricityShift(D(20))])
    both = whatif.run(
        acts,
        [
            whatif.ActivityChange("Diesel", D(15)),
            whatif.ActivityChange("Coal (boiler)", D(10)),
            whatif.ElectricityShift(D(20)),
        ],
    )
    assert close(a.avoided_co2e_t, "0.8208582345", "1e-9") and a.cost_saved_inr == D(27000)
    assert close(b.avoided_co2e_t, "1.891155", "1e-9") and b.cost_saved_inr == D(9000)
    assert close(c.avoided_co2e_t, "2.6172", "1e-9") and c.cost_saved_inr == D(28800)
    assert close(both.avoided_co2e_t, "5.3292132345", "1e-9") and both.cost_saved_inr == D(64800)
    assert close(both.pct_of_total, "13.676", "1e-3")


def test_overlapping_scenarios_apply_in_sequence_not_added():
    acts = factory()
    two = whatif.run(
        acts, [whatif.ActivityChange("Diesel", D(10)), whatif.ActivityChange("Diesel", D(10))]
    )
    # 0.9 x 0.9 = 0.81, so 19% is avoided, not 20%: 0.19 x 5.47238823 = 1.0397537637
    assert close(two.avoided_co2e_t, "1.0397537637", "1e-9")


def test_fuel_switch_by_energy_equivalence():
    # coal 10,000 kg alone: 0.196 TJ at 96.4875 t/TJ CO2e. Moving 50% (0.098 TJ) to LPG at
    # 63.2665 t/TJ: avoided = 0.098 x (96.4875 - 63.2665) = 3.255658 t
    acts = [act("coal", "10000", "kg", "estimated", None, "Coal")]
    out = whatif.run(acts, [whatif.FuelSwitch("Coal", D(50), "lpg", to_label="LPG")])
    assert close(out.avoided_co2e_t, "3.255658", "1e-9")
    assert out.cost_saved_inr is None  # no costs given, so the cost effect is unknown


def test_electricity_shift_with_a_replacement_factor():
    out = whatif.run(factory(), [whatif.ElectricityShift(D(20), other_ef_t_per_mwh=D("0.1"))])
    assert close(out.avoided_co2e_t, "2.2572", "1e-9")  # 2.6172 - 3.6 MWh x 0.1


def test_bad_scenarios_are_refused():
    with pytest.raises(whatif.ScenarioError, match="no activity"):
        whatif.run(factory(), [whatif.ActivityChange("Nothing", D(10))])
    with pytest.raises(whatif.ScenarioError, match="between 0 and 100"):
        whatif.run(factory(), [whatif.ActivityChange("Diesel", D(150))])
    with pytest.raises(whatif.ScenarioError, match="exactly one grid"):
        whatif.run(
            [act("coal", "1", "t", "default", None, "Coal")], [whatif.ElectricityShift(D(5))]
        )
    dup = [act("coal", "1", "t", "default", None, "Coal")] * 2
    with pytest.raises(whatif.ScenarioError, match="distinct"):
        whatif.run(dup, [whatif.ActivityChange("Coal", D(5))])


def test_abatement_cost():
    assert whatif.abatement_cost(D(100000), D(40000), D(12)) == D(5000)
    assert whatif.abatement_cost(D(10000), D(40000), D(12)) == D(-2500)  # pays for itself
    with pytest.raises(whatif.ScenarioError):
        whatif.abatement_cost(D(1), D(1), D(0))


# ---- recommendations -----------------------------------------------------------------------
def test_recommendations_follow_hotspot_equipment_and_data_class():
    fp = calculate(factory())
    rows = hotspot.pareto(fp)
    eq = {a.name: a.equipment for a in factory()}
    recs = recommend.recommend(rows, eq, top=3)
    by = {(r.hotspot, r.rule_id) for r in recs}
    assert ("Coal (boiler)", "boiler_solid") in by
    assert ("Coal (boiler)", "data") in by  # estimated, so improve the data
    assert ("Grid electricity", "electricity") in by
    assert ("Grid electricity", "data") not in by  # measured
    assert all(r.sources for r in recs)


def test_no_equipment_tag_means_only_untagged_rules_apply():
    rows = hotspot.pareto(calculate([act("coal", "10000", "kg", "measured", None, "Coal")]))
    assert recommend.recommend(rows, {"Coal": ""}) == []
