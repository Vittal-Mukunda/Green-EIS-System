"""The aggregate ASI facts behind the Gap 1, 3 and 4 pages, against a hand-worked toy file.

Toy factories (records laid out as in test_study_asi.py):

    700001 (10 persons): electricity 1,000 kWh for Rs 8,000; coal 500 kg for Rs 5,000;
                         petrol/diesel/oil line: a value of Rs 3,000 and no quantity
    700002 (10 persons): electricity 2,000 kWh for Rs 16,000
    700003 (10 persons): petrol/diesel/oil line only: Rs 1,000, no quantity
    700004 (10 persons): no input records at all
    700005 (80 persons): electricity, too large to be small

Emissions by hand (CSTEP/CEA factors in the library):

    electricity 1,000 kWh = 1 MWh x 0.727 t/MWh = 0.727 t; 2,000 kWh = 1.454 t
    coal 500 kg = 0.0005 kt x 19.6 TJ/kt = 0.0098 TJ
        CO2  0.0098 x 95,810 / 1000 = 0.938938 t
        CH4  0.0098 x 10 / 1000 x 28 = 0.002744 t; N2O 0.0098 x 1.5 / 1000 x 265 = 0.0038955 t
        total 0.9455775 t
    totals: spend 29,000; emissions 0.727 + 1.454 + 0.9455775 = 3.1265775 t
    electricity share of spend 24,000 / 29,000 = 0.82759; of emissions 2.181 / 3.1265775 = 0.69757
    coal share of spend 5,000 / 29,000 = 0.17241; of emissions 0.9455775 / 3.1265775 = 0.30243
    rupees per tCO2e: electricity 8,000 / 0.727 = 16,000 / 1.454 = 11,004.13; coal 5,000 / 0.9455775 = 5,287.8
    factory 700001 (the only one with two fuels): total 1.6725775 t; coal share 0.56535, lead over
        electricity 0.13068; its biggest cost is electricity (Rs 8,000 > 5,000), its biggest emitter coal
"""

from __future__ import annotations

import pytest

from greeneis.study import asi, gap_evidence
from test_study_asi import a_rec, e_rec, h_rec, write


@pytest.fixture
def toy(tmp_path):
    recs = []
    for dsl, persons in [
        ("700001", 10),
        ("700002", 10),
        ("700003", 10),
        ("700004", 10),
        ("700005", 80),
    ]:
        recs += [a_rec(dsl), e_rec(dsl, persons)]
    recs += [
        h_rec("700001", "9990500", 28, 1000, 8000),
        h_rec("700001", "9990700", 9, 500, 5000, sl=2),
        h_rec("700001", "9990600", 0, 0, 3000, sl=3),
        h_rec("700002", "9990500", 28, 2000, 16000),
        h_rec("700003", "9990600", 0, 0, 1000),
        h_rec("700005", "9990500", 28, 5000, 40000),
    ]
    blocks = asi.read_blocks(write(tmp_path, *recs))
    return blocks, asi.build_cases(blocks, 50).cases


def test_the_toy_case_table_is_what_the_comments_say(toy):
    _, cases = toy
    assert sorted(cases["unit_id"].unique()) == ["ASI2023-24-700001", "ASI2023-24-700002"]
    assert len(cases) == 3


def test_cost_link_by_hand(toy):
    _, cases = toy
    rows = {r["item"]: r for r in gap_evidence.fuel_cost_link(cases)}
    e, c = rows["grid_electricity"], rows["coal"]
    assert (e["records"], c["records"]) == (2, 1)
    assert e["spend_inr"] == 24000 and c["spend_inr"] == 5000
    assert e["co2e_t"] == pytest.approx(2.181, abs=1e-6)
    assert c["co2e_t"] == pytest.approx(0.9455775, abs=1e-6)
    assert e["spend_share"] == pytest.approx(0.82759, abs=1e-5)
    assert c["spend_share"] == pytest.approx(0.17241, abs=1e-5)
    assert e["co2e_share"] == pytest.approx(0.69757, abs=1e-5)
    assert c["co2e_share"] == pytest.approx(0.30243, abs=1e-5)
    assert e["inr_per_tco2e_pooled"] == pytest.approx(11004.13, abs=0.01)
    assert e["inr_per_tco2e_median"] == pytest.approx(11004.13, abs=0.01)
    assert c["inr_per_tco2e_pooled"] == pytest.approx(5287.8, abs=0.1)
    assert [r["item"] for r in gap_evidence.fuel_cost_link(cases)] == [
        "grid_electricity",
        "coal",
    ]  # by total emissions
    assert sum(r["spend_share"] for r in rows.values()) == pytest.approx(1.0)
    assert sum(r["co2e_share"] for r in rows.values()) == pytest.approx(1.0)


def test_hotspot_structure_by_hand(toy):
    _, cases = toy
    h = gap_evidence.hotspot_structure(cases)
    assert (h["factories_with_a_fuel"], h["single_fuel_factories"], h["multi_fuel_factories"]) == (
        2,
        1,
        1,
    )
    assert h["top_share_median"] == pytest.approx(0.56535, abs=1e-4)
    assert h["lead_median"] == pytest.approx(0.13068, abs=1e-4)
    assert h["thin_lead_factories"] == 0  # a lead of 0.13 is not under 0.10
    assert h["top_item_counts"] == {"coal": 1}
    assert h["biggest_cost_not_biggest_emitter"] == 1


def test_a_thin_lead_is_counted(toy):
    _, cases = toy
    assert gap_evidence.hotspot_structure(cases, thin_below=0.20)["thin_lead_factories"] == 1


def test_reporting_coverage_by_hand(toy):
    blocks, cases = toy
    cov = gap_evidence.reporting_coverage(blocks, 50, cases)
    assert cov["small_factories"] == 4  # 700005 has 80 persons
    assert cov["usable_quantity"] == 2
    assert cov["no_quantity_lines"]["Petrol, diesel and oil"] == 2  # 700001 and 700003
    assert cov["no_quantity_lines"]["Other fuel"] == 0
    assert cov["spend_without_quantity_any_line"] == 2
    assert cov["usable_and_spend_without_quantity"] == 1  # 700001
    assert cov["spend_without_quantity_only"] == 1  # 700003
    assert cov["neither"] == 1  # 700004
    parts = cov["usable_quantity"] + cov["spend_without_quantity_only"] + cov["neither"]
    assert parts == cov["small_factories"]  # every small factory is in exactly one group


def test_compute_gathers_the_three_blocks_and_marks_them_real(toy):
    blocks, _ = toy
    out = gap_evidence.compute(blocks)
    assert set(out) == {"provenance", "coverage", "cost_link", "hotspots"}
    prov = out["provenance"]
    assert prov["synthetic"] is False and prov["aggregates_only"] is True
    assert "not metered" in prov["reference_quantity"]
    assert prov["data_log"]["small (persons <= max_employees)"] == 4
