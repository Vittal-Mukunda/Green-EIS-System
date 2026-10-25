"""The engine against CSTEP's published tables (ref S1, Tables 7 and 8, read from the PDF).

These tests record a finding about the published report, not a requirement of the engine: the cells
listed in FLAGGED disagree with the report's own factors (Tables 2-4). They are flagged, never corrected.
"""

from __future__ import annotations

from decimal import Decimal as D

from greeneis.validation import compare_cstep, flagged

FLAGGED = {
    ("LPG", "2015-16"),
    *{
        ("Naphtha", y)
        for y in (
            "2008-09",
            "2009-10",
            "2010-11",
            "2011-12",
            "2012-13",
            "2013-14",
            "2014-15",
            "2015-16",
        )
    },
    ("FO", "2012-13"),
    ("FO", "2013-14"),
    ("FO", "2014-15"),
    ("FO", "2015-16"),
}


def test_all_56_cells_are_compared():
    assert len(compare_cstep()) == 56


def test_the_flagged_cells_are_exactly_the_known_disagreements():
    assert {(c.column, c.year) for c in flagged()} == FLAGGED


def test_diesel_oils_kerosene_and_lshs_reproduce_in_every_year():
    ok = {(c.column, c.year) for c in compare_cstep() if c.matches}
    for column in ("HSDO", "LDO", "Kerosene", "LSHS"):
        for year in (
            "2008-09",
            "2009-10",
            "2010-11",
            "2011-12",
            "2012-13",
            "2013-14",
            "2014-15",
            "2015-16",
        ):
            assert (column, year) in ok, (column, year)


def test_furnace_oil_from_2012_13_is_about_a_tenth_of_what_the_factors_imply():
    # by hand: 2015-16, 2,564 kt x 40.2 x 77.643 / 1e6 = 8.0029 Mt against 0.84 printed (ratio 0.105)
    cell = next(c for c in compare_cstep() if (c.column, c.year) == ("FO", "2015-16"))
    assert abs(cell.recomputed_mt - D("8.0028814104")) < D("1e-9")
    assert D("0.09") < cell.ratio < D("0.16")
    for year in ("2012-13", "2013-14", "2014-15", "2015-16"):
        c = next(c for c in compare_cstep() if (c.column, c.year) == ("FO", year))
        assert D("0.09") <= c.ratio.quantize(D("0.01")) <= D("0.16")
