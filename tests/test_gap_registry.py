"""The registries of research gaps and references, and the factor arithmetic behind the Gap 5 page.

The gap list is Table 5.1 of the reference document: seven gaps, in that order, with that wording. The
break-even literals are worked by hand from the library's factors:

    coal   : 95,810 + 28 x 10 + 265 x 1.5 = 96,487.5 kg CO2e per TJ  -> 96.4875 kg per GJ
    LPG    : 63,100 + 28 x 5 + 265 x 0.1  =  63,266.5 kg per TJ      -> 63.2665 kg per GJ
    grid   : 0.727 t/MWh = 727 kg per MWh, and 1 MWh = 3.6 GJ         -> 727 / 3.6 = 201.9444 kg per GJ
    break-even (coal) = 96.4875 / 201.9444 = 0.47779; (LPG) = 63.2665 / 201.9444 = 0.31329
"""

from __future__ import annotations

import re
from decimal import Decimal as D

import pytest

from greeneis import gaps, references, whatif

TABLE_5_1 = [
    "No firm-level, regularly updated fuel and energy data for informal units",
    "Estimates carry unquantified uncertainty and numbers conflict across studies",
    "National studies do not tell a single factory what to fix first",
    "Emissions are not linked to cost, but energy is a large share of MSME cost and prices are volatile",
    "Decarbonisation evidence is cluster-level and requires audits and engineers",
    "SME carbon tools exist but demand data, expertise or fees, and few are India- and MSME-fuel-specific",
    "Suppliers face growing buyer demands for emission data but lack the means to respond",
]


# ---- gaps ---------------------------------------------------------------------------------------
def test_the_registry_holds_exactly_the_seven_gaps_of_table_5_1_in_order():
    assert [g.number for g in gaps.GAPS] == [1, 2, 3, 4, 5, 6, 7]
    assert [g.title for g in gaps.GAPS] == TABLE_5_1


def test_identifiers_labels_and_slugs_are_unique():
    for attr in ("id", "nav_label", "slug", "short", "question"):
        values = [getattr(g, attr) for g in gaps.GAPS]
        assert len(set(values)) == len(values), attr
    assert (
        gaps.get(3).id == "G3"
        and gaps.by_slug("gap-3").number == 3
        and gaps.by_slug("gap-9") is None
    )


def test_every_source_resolves_to_a_reference_and_every_gap_names_one():
    for g in gaps.GAPS:
        assert g.sources, g.id
        for s in g.sources:
            assert references.get(s.ref).key == s.ref  # a typo would raise KeyError


def test_a_gap_is_never_attributed_more_firmly_than_its_sources_allow():
    for g in gaps.GAPS:
        origin = g.originating()
        if g.attribution == "verified":
            # a verified attribution needs an originating paper that was read in the original
            assert origin and all(r.verification == "read_original" for r in origin), g.id
        else:
            assert g.attribution in ("interpretation", "unverified")
    # gaps 4 to 7 rest on abstracts and trade material: none may claim a verified origin
    assert all(gaps.get(n).attribution != "verified" for n in (4, 5, 6, 7))


def test_statuses_are_modest_and_follow_the_evidence():
    status = {g.number: g.status for g in gaps.GAPS}
    assert "addressed" not in status.values()  # nothing is settled by a stand-in dataset alone
    assert status[5] == status[6] == status[7] == "insufficient"  # no data can test these
    assert all(g.status_reason and g.limits and g.missing for g in gaps.GAPS)


def test_no_gap_text_overclaims():
    banned = ("first tool", "solved", "closed the gap", "certified emissions", "proves", "proven")
    for g in gaps.GAPS:
        text = " ".join(
            [g.greeneis_does, g.evidence, g.status_reason, g.attribution_note, g.found]
        ).lower()
        for word in banned:
            assert not re.search(rf"{word}", text), (g.id, word)


# ---- references ---------------------------------------------------------------------------------
def test_references_have_unique_keys_and_no_duplicate_links():
    keys = [r.key for r in references.REFERENCES]
    assert len(set(keys)) == len(keys)
    links = [r.link for r in references.REFERENCES if r.link]
    assert len(set(links)) == len(links)


def test_every_reference_is_a_known_category_and_verification_level():
    for r in references.REFERENCES:
        assert r.category in references.CATEGORIES and r.verification in references.VERIFICATION
        assert r.title and r.venue is not None


def test_a_dois_form_is_checked_and_the_link_prefers_it():
    kuo = references.get("kuo2015")
    assert kuo.doi == "10.1007/s40684-015-0006-y"
    assert kuo.link == "https://doi.org/10.1007/s40684-015-0006-y"
    assert references.get("cstep2018").link.startswith("http")


def test_in_text_short_forms_by_hand():
    assert references.get("kuo2015").short == "Kuo et al. (2015)"
    assert references.get("weidema1996").short == "Weidema and Wesnaes (1996)"
    assert references.get("dte2022").short == "Upadhyay (2022)"
    assert references.get("cstep2018").short == "CSTEP (2018)"


def test_sources_not_verified_in_the_original_say_so():
    for key in ("zocca2018", "helo2024", "t20_brief", "digital_reporting", "holm1979"):
        assert references.get(key).verification == "unverified", key
    assert references.get("cstep2018").verification == "read_original"
    assert references.get("ceew2018").verification == "read_original"


def test_citation_style_is_consistent():
    text = references.citation(references.get("efron1979"))
    assert text.startswith("Efron, B. (1979). Bootstrap methods: another look at the jackknife.")
    assert text.endswith("https://doi.org/10.1214/aos/1176344552")
    # authors or year not established are said, not guessed
    assert "(year not established)" in references.citation(
        references.Reference("x", "supporting", "Someone", "", "A title", "", "unverified")
    )


def test_reference_labels_map_back_to_the_reference_document():
    assert references.by_ref_id("S7").key == "energetica2024"
    assert references.by_ref_id("S99") is None


def test_a_bad_category_or_level_is_refused():
    with pytest.raises(ValueError):
        references.Reference("x", "nonsense", "", "", "t", "", "unverified")
    with pytest.raises(ValueError):
        references.Reference("x", "supporting", "", "", "t", "", "certified")


# ---- factor arithmetic for the Gap 5 page --------------------------------------------------------
def test_intensity_per_gigajoule_by_hand():
    assert whatif.kg_co2e_per_gj("coal") == D("96.4875")
    assert whatif.kg_co2e_per_gj("lpg") == D("63.2665")
    assert float(whatif.kg_co2e_per_gj("grid_electricity")) == pytest.approx(201.9444, abs=1e-4)


def test_electrification_break_even_by_hand():
    assert float(whatif.electrification_breakeven("coal")) == pytest.approx(0.47779, abs=1e-5)
    assert float(whatif.electrification_breakeven("lpg")) == pytest.approx(0.31329, abs=1e-5)
