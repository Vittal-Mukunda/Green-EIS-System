"""National estimates and the plain readings of a study result.

Expected values are copied by hand from the published reports (as recorded in docs/FINDINGS.md) and from
outputs/study_asi_2023-24*.json; none is recomputed with the code under test.
"""

from __future__ import annotations

import pathlib
from decimal import Decimal as D

import pytest

from greeneis.national import NationalError, load_national, parse
from greeneis.study.headline import headline, load

OUTPUTS = pathlib.Path(__file__).resolve().parents[1] / "outputs"


def row(**kw):
    base = {
        "id": "x",
        "label": "A figure",
        "value_low": "1",
        "value_high": "2",
        "unit": "Mt",
        "year": "2015-16",
        "source": "A source",
        "status": "read_in_original",
        "note": "",
    }
    return {**base, **kw}


def test_published_national_figures_are_as_read_in_the_reports():
    n = load_national()
    assert n["cstep_informal_total"].low == D("110") and n["cstep_informal_total"].unit == "MtCO2e"
    assert n["ceew_informal_total"].low == D("105") and n["ceew_informal_total"].year == "2015-16"
    assert n["ceew_brick_coal"].low == D("26") and n["ceew_brick_coal"].unit == "Mt coal"
    assert (n["cpcb_brick_coal"].low, n["cpcb_brick_coal"].high) == (D("35"), D("40"))
    assert (n["mnre_brick_coal"].low, n["mnre_brick_coal"].high) == (D("46"), D("69.1"))
    assert n["mnre_brick_coal"].is_range and not n["ceew_brick_coal"].is_range


def test_every_national_figure_carries_a_unit_a_source_a_year_and_a_status():
    for est in load_national().values():
        assert est.unit and est.source and est.year, est.id
        assert est.status in ("read_in_original", "cited_by_original"), est.id


@pytest.mark.parametrize("column", ["unit", "source", "year", "value_low", "status"])
def test_an_estimate_without_provenance_is_refused(column):
    with pytest.raises(NationalError):
        parse([row(**{column: ""})])


def test_bad_rows_are_refused():
    with pytest.raises(NationalError):
        parse([row(value_low="abc")])
    with pytest.raises(NationalError):
        parse([row(value_low="5", value_high="2")])
    with pytest.raises(NationalError):
        parse([row(status="guess")])
    with pytest.raises(NationalError):
        parse([row(), row()])


def test_the_main_asi_result_reads_as_recorded_by_hand():
    h = load(OUTPUTS / "study_asi_2023-24.json")
    assert (h.factories, h.records, h.states) == (24154, 26664, 36)
    assert not h.synthetic and h.only_sector is None
    assert h.estimated_median == pytest.approx(0.0625, abs=1e-3)
    assert h.default_median == pytest.approx(0.748, abs=1e-3)
    assert h.default_q90 == pytest.approx(5.99, abs=1e-2)
    assert (h.placeholder_estimated, h.placeholder_default) == (0.25, 0.5)
    assert h.coverage_by_profile["minimal"] == pytest.approx(0.318, abs=1e-3)
    assert h.top1_kept == pytest.approx(0.964, abs=1e-3)
    assert h.top1_thin_lead == pytest.approx(0.574, abs=1e-3)
    assert h.h5_rows == 67
    assert set(h.verdicts.values()) == {"supported"}
    assert h.multi_item_factories == 2442 and h.factories_in_file == 68641
    assert h.placeholder_status == "placeholder"


def test_fuels_are_ordered_by_records_with_their_own_errors():
    h = load(OUTPUTS / "study_asi_2023-24.json")
    assert [f.item for f in h.fuels] == ["grid_electricity", "lpg", "coal"]
    elec, lpg, coal = h.fuels
    assert elec.name == "Electricity" and elec.records == 24104
    assert elec.estimated_median == pytest.approx(0.0567, abs=1e-3)
    assert coal.estimated_median == pytest.approx(0.172, abs=1e-3)
    assert coal.estimated_q90 == pytest.approx(0.631, abs=1e-3)
    assert lpg.estimated_q90 == pytest.approx(0.575, abs=1e-3)


def test_the_textile_cut_is_marked_and_its_weak_tests_are_named():
    h = load(OUTPUTS / "study_asi_2023-24_explor_nic13.json")
    assert h.only_sector == "NIC13" and h.factories == 1105
    assert h.verdicts["H4"] == "not supported" and h.verdicts["H5"] == "insufficient data"
    assert h.h5_reduction == {}  # no estimate when data are insufficient


def test_a_file_that_is_not_a_study_result_is_refused():
    with pytest.raises(KeyError):
        headline({"unrelated": 1})
