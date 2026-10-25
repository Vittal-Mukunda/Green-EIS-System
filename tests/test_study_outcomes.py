"""Profile evaluation against a hand-worked unit.

Unit U1: grid 1000 kWh, coal 1000 kg, diesel 500 kg. Coefficients (tCO2e per kWh or kg), by hand:
    grid 0.727 / 1000 = 0.000727
    coal 19.6e-6 kt/kg x 96.4875 t/TJ = 0.001891155        (96.4875 = 95.81 + 10 x 28/1000 + 1.5 x 265/1000)
    diesel 43.3e-6 x 74.343 = 0.0032190519
Reference emissions: 0.727, 1.891155, 1.60952595; total 4.22768095. Proxies given: estimated quantities
(1000, 1200, 400) and default quantities (2000, 600, 900).

bills_only (grid Measured; coal and diesel Estimated): degraded 0.727, 2.269386, 1.28762076 = 4.28400676
    relative error 0.0563258 / 4.22768095 = 0.0133231
    T = (0.727 + 0.6 x 3.55700676) / 4.28400676 = 0.66788
minimal (all Default): 1.454, 1.134693, 2.89714671 = 5.48583971; the top item flips from coal to diesel.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from greeneis.engine import Activity, calculate_activity
from greeneis.study.outcomes import (
    PROFILES,
    assign_classes,
    coefficients,
    evaluate,
)


def unit_frame(unit="U1", cluster="C1"):
    return pd.DataFrame(
        {
            "unit_id": unit,
            "item_id": ["grid_electricity", "coal", "diesel"],
            "cluster": cluster,
            "quantity": [1000.0, 1000.0, 500.0],
            "q_estimated": [1000.0, 1200.0, 400.0],
            "q_default": [2000.0, 600.0, 900.0],
            "eps_estimated": [0.0, 0.2, -0.2],
            "eps_default": [1.0, -0.4, 0.8],
        }
    )


def row(data, profile):
    return data.profiles[data.profiles["profile"] == profile].iloc[0]


def test_coefficients_match_the_hand_values_and_the_engine():
    k = coefficients()
    assert k["grid_electricity"] == pytest.approx(0.000727, rel=1e-12)
    assert k["coal"] == pytest.approx(0.001891155, rel=1e-12)
    assert k["diesel"] == pytest.approx(0.0032190519, rel=1e-12)
    from decimal import Decimal

    ten = calculate_activity(Activity("coal", Decimal(10000), "kg")).co2e_t
    assert float(ten) == pytest.approx(k["coal"] * 10000)


def test_bills_only_profile_by_hand():
    r = row(evaluate(unit_frame()), "bills_only")
    assert r.total_ref == pytest.approx(4.22768095)
    assert r.total_deg == pytest.approx(4.28400676)
    assert r.rel_error == pytest.approx(0.0133231, abs=1e-7)
    assert r.trust_index == pytest.approx(0.66788, abs=1e-5)
    assert r.uncertainty == pytest.approx(0.152502, abs=1e-6)
    assert bool(r.covered) is True
    assert (r.n_measured, r.n_estimated, r.n_default) == (1, 2, 0)
    assert r.top1_match == 1.0
    assert r.lead_gap_ref == pytest.approx(0.0666155, abs=1e-7)
    assert r.top_class == "estimated"  # the reference top item (coal) is Estimated in this profile


def test_minimal_profile_flips_the_top_hotspot():
    r = row(evaluate(unit_frame()), "minimal")
    assert r.total_deg == pytest.approx(5.48583971)
    assert r.rel_error == pytest.approx(0.2976002, abs=1e-7)
    assert r.trust_index == pytest.approx(0.3)
    assert r.top1_match == 0.0
    assert r.default_share_deg == pytest.approx(1.0)


def test_invoices_main_measures_grid_and_the_largest_fuel_only():
    r = row(evaluate(unit_frame()), "invoices_main")
    assert (r.n_measured, r.n_estimated, r.n_default) == (
        2,
        1,
        0,
    )  # grid + coal measured, diesel estimated
    # degraded: 0.727 + 1.891155 + 400 x 0.0032190519 = 3.90577576 (diesel underestimated)
    assert r.total_deg == pytest.approx(3.90577576)


def test_random_mix_is_reproducible_and_seed_dependent():
    a = evaluate(unit_frame(), seed=1).profiles
    b = evaluate(unit_frame(), seed=1).profiles
    pd.testing.assert_frame_equal(a, b)
    draws = {
        tuple(
            assign_classes(
                "random_mix",
                np.array(["a", "b", "c", "d", "e", "f"]),
                np.ones(6),
                np.random.default_rng([s, 0, 3]),
            )
        )
        for s in range(20)
    }
    assert len(draws) > 1


def test_h5_gains_by_hand():
    data = evaluate(unit_frame())
    r = data.h5[data.h5["profile"] == "bills_only"].iloc[0]
    # upgrading coal: error goes 0.0133231 -> 0.0761423, a gain of -0.0628192; diesel: -0.0761423
    assert r.n_candidates == 2
    assert r.base_abs_error == pytest.approx(0.0133231, abs=1e-7)
    assert r.r_largest == pytest.approx(
        -0.0628192, abs=1e-7
    )  # coal has the larger degraded emissions
    assert r.r_random == pytest.approx(-0.0694807, abs=1e-7)  # the mean of the two gains
    assert r.r_lowest in (
        pytest.approx(-0.0628192, abs=1e-7),
        pytest.approx(-0.0761423, abs=1e-7),
    )  # both Estimated: a random tie-break


def test_unit_with_one_candidate_has_no_h5_row_and_one_item_has_no_hotspot_metrics():
    one = unit_frame().head(1)
    data = evaluate(one)
    assert data.h5.empty
    assert np.isnan(row(data, "minimal").top1_match)


def test_units_with_missing_proxies_are_excluded_and_counted():
    df = unit_frame()
    df.loc[1, "q_estimated"] = np.nan
    data = evaluate(df)
    assert "bills_only: a needed proxy could not be formed" in data.excluded
    assert "bills_only" not in set(data.profiles["profile"])
    assert "minimal" in set(data.profiles["profile"])  # default proxies are all present


def test_all_profiles_are_known_and_unknown_is_refused():
    assert set(evaluate(unit_frame()).profiles["profile"]) == set(PROFILES)
    with pytest.raises(ValueError, match="unknown profile"):
        assign_classes("nonsense", np.array(["coal"]), np.ones(1), np.random.default_rng(0))
