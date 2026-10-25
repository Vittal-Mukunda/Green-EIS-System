"""The engine against hand calculations. Expected values are worked out by hand from the printed CSTEP
factors (Tables 2-4 of ref S1) and the CEA grid factor, never by calling the code under test.

Hand calculation, coal 10,000 kg = 0.01 kt:
    energy = 0.01 x 19.6 = 0.196 TJ
    CO2  = 0.196 x 95,810 / 1000 = 18.77876 t   (0.196 x 95.81 = 19.162 - 0.38324)
    CH4  = 0.196 x 10 kg = 1.96 kg;  as CO2e = 1.96 x 28 = 54.88 kg = 0.05488 t
    N2O  = 0.196 x 1.5 kg = 0.294 kg; as CO2e = 0.294 x 265 = 77.91 kg = 0.07791 t
    CO2e = 18.77876 + 0.05488 + 0.07791 = 18.91155 t
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from greeneis.engine import Activity, EngineError, calculate, calculate_activity, canonical_quantity
from greeneis.factors import FactorError, FactorLibrary, default_library, parse_fuels


def act(item, qty, unit, **kw):
    return Activity(item_id=item, quantity=D(qty), unit=unit, **kw)


def test_coal_10000_kg_by_hand():
    r = calculate_activity(act("coal", "10000", "kg"))
    assert r.energy_tj == D("0.196")
    assert r.co2_t == D("18.77876")
    assert r.ch4_t == D("0.00196")
    assert r.n2o_t == D("0.000294")
    assert r.co2e_t == D("18.91155")
    assert "coal_grade_assumed" in r.flags


def test_diesel_2000_litres_by_hand():
    # 2000 L x 0.85 kg/L = 1700 kg = 0.0017 kt; energy 0.0017 x 43.3 = 0.07361 TJ
    # CO2 0.07361 x 74,100/1000 = 5.454501 t; CH4 0.07361 x 3 x 28 = 6.18324 kg;
    # N2O 0.07361 x 0.6 x 265 = 11.70399 kg; total 5.454501 + 0.00618324 + 0.01170399
    r = calculate_activity(act("diesel", "2000", "L"))
    assert r.energy_tj == D("0.07361")
    assert r.co2e_t == D("5.47238823")
    assert "assumed_density" in r.flags


def test_lpg_500_kg_by_hand():
    # 0.0005 kt x 47.3 = 0.02365 TJ; CO2 0.02365 x 63,100/1000 = 1.492315; CH4 0.02365 x 5 x 28 =
    # 3.311 kg; N2O 0.02365 x 0.1 x 265 = 0.626725 kg
    r = calculate_activity(act("lpg", "500", "kg"))
    assert r.energy_tj == D("0.02365")
    assert r.co2e_t == D("1.496252725")


def test_grid_18000_kwh_by_hand():
    # 18 MWh x 0.727 = 13.086 tCO2; energy 18 x 0.0036 = 0.0648 TJ
    r = calculate_activity(act("grid_electricity", "18000", "kWh"))
    assert r.co2e_t == D("13.086")
    assert r.energy_tj == D("0.0648")
    assert r.factor_id == "cea_v20_2023_24_avg"


def test_reference_document_worked_example_total():
    # ref section 7: 13.086 + 18.91155 + 5.47238823 + 1.496252725 = 38.966190955 (the document's 38.97)
    fp = calculate(
        [
            act("grid_electricity", "18000", "kWh"),
            act("coal", "10000", "kg"),
            act("diesel", "2000", "L"),
            act("lpg", "500", "kg"),
        ]
    )
    assert fp.total_co2e_t == D("38.966190955")


def test_cstep_hsdo_2008_09_row():
    # 1,469 kt x 43.3 = 63,607.7 TJ; combined factor 74.1 + 3 x 28/1000 + 0.6 x 265/1000 = 74.343 t/TJ
    # 63,607.7 x 74.343 = 4,728,787.2411 t (CSTEP prints 4.70 Mt: within 1%)
    r = calculate_activity(act("diesel", "1469", "kt"))
    assert r.co2e_t == D("4728787.2411")


def test_cstep_furnace_oil_2015_16_row():
    # 2,564 kt x 40.2 = 103,072.8 TJ; combined 77.4 + 0.084 + 0.159 = 77.643 t/TJ
    # 103,072.8 x 77.643 = 8,002,881.4104 t, against 0.84 Mt printed by CSTEP (flagged in validation)
    r = calculate_activity(act("furnace_oil", "2564", "kt"))
    assert r.co2e_t == D("8002881.4104")


def test_units_are_exact_and_interchangeable():
    kg = calculate_activity(act("coal", "10000", "kg"))
    t = calculate_activity(act("coal", "10", "t"))
    kt = calculate_activity(act("coal", "0.01", "kt"))
    assert kg.co2e_t == t.co2e_t == kt.co2e_t == D("18.91155")
    assert calculate_activity(act("grid_electricity", "18", "MWh")).co2e_t == D("13.086")
    assert calculate_activity(act("diesel", "2", "kL")).co2e_t == D("5.47238823")


def test_gwp_is_a_parameter():
    # with GWP 1 for both gases: 18.77876 + 0.00196 + 0.000294 = 18.781014
    r = calculate_activity(act("coal", "10000", "kg"), gwp={"ch4": D(1), "n2o": D(1)})
    assert r.co2e_t == D("18.781014")


@pytest.mark.parametrize(
    "item,qty,unit,message",
    [
        ("peat", "1", "kg", "no factor for fuel"),
        ("natural_gas", "100", "m3", "volumetric gas"),
        ("lpg", "100", "L", "no density"),
        ("coal", "1", "bucket", "not supported"),
        ("grid_electricity", "1", "kg", "kWh, MWh or GWh"),
        ("coal", "-1", "kg", "negative"),
    ],
)
def test_refuses_what_it_cannot_calculate(item, qty, unit, message):
    with pytest.raises(EngineError, match=message):
        calculate_activity(act(item, qty, unit))


def test_bad_data_class_is_refused():
    with pytest.raises(EngineError, match="data_class"):
        act("coal", "1", "kg", data_class="guessed")


def test_unknown_grid_id_is_refused():
    with pytest.raises(EngineError, match="no grid factor"):
        calculate_activity(act("grid_electricity", "1", "kWh", grid_id="nope"))


def test_library_rows_all_carry_value_source_year_and_status():
    lib = default_library()
    assert len(lib.fuels) == 9
    for f in lib.fuels:
        assert f.source and 1990 <= f.source_year <= 2100 and f.status
        assert f.ncv_tj_per_kt > 0 and f.ef_co2_kg_per_tj > 0
    for g in lib.grids:
        assert g.source and g.status == "source_verified" and g.ef_t_co2_per_mwh > 0


def test_library_refuses_a_factor_without_a_source():
    row = {
        "id": "x",
        "name": "X",
        "phase": "solid",
        "ncv_tj_per_kt": "1",
        "ef_co2_kg_per_tj": "1",
        "ef_ch4_kg_per_tj": "1",
        "ef_n2o_kg_per_tj": "1",
        "source": "",
        "source_year": "2018",
        "status": "source_verified",
    }
    with pytest.raises(FactorError, match="source"):
        parse_fuels([row])
    row["source"] = "S"
    row["source_year"] = ""
    with pytest.raises(FactorError, match="source_year"):
        parse_fuels([row])
    row["source_year"] = "2018"
    row["status"] = "trust_me"
    with pytest.raises(FactorError, match="status"):
        parse_fuels([row])


def test_unknown_fuel_lookup_names_the_known_ones():
    with pytest.raises(FactorError, match="coal"):
        FactorLibrary.from_directory().fuel("peat")


def test_no_silent_float_drift():
    # a sum of many small exact decimals stays exact
    fp = calculate([act("lpg", "0.1", "kg")] * 10)
    one = calculate_activity(act("lpg", "1", "kg"))
    assert fp.total_co2e_t == one.co2e_t


def test_canonical_quantity_by_hand():
    # 2000 L x 0.85 kg/L = 1700 kg; 18 MWh = 18,000 kWh; 10 t = 10,000 kg; 2 kt = 2,000,000 kg
    assert canonical_quantity(act("diesel", "2000", "L")) == (D("1700.00"), "kg")
    assert canonical_quantity(act("grid_electricity", "18", "MWh")) == (D("18000"), "kWh")
    assert canonical_quantity(act("coal", "10", "t")) == (D("10000"), "kg")
    assert canonical_quantity(act("coal", "2", "kt")) == (D("2000000"), "kg")
    with pytest.raises(EngineError):
        canonical_quantity(act("lpg", "1", "L"))
