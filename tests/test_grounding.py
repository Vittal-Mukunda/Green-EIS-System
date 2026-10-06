"""Grounding: claim extraction, unit normalisation and the supported / unsupported / wrong labels."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from gauge.config import load_indicators
from gauge.db.models import Annotation, Claim, Judgment, Run
from gauge.db.session import session_scope
from gauge.evaluate.grounding import (
    ClaimedNumber,
    ClaimResult,
    ClaimStoreError,
    Shown,
    extract_numbers,
    label_justification,
    label_number,
    mention_pattern,
    mentioned_codes,
    shown_values,
    split_clauses,
    store_claims,
)
from gauge.render.runs import render_run_prompts
from gauge.runcmd import stage_parse
from gauge.runner.execute import execute_run
from gauge.stats.primitives import NAN  # noqa: F401  (keeps the import style uniform)
from helpers import CannedRunner, good_item

D = Decimal
CRORE = Decimal(10**7)


@pytest.fixture(scope="module")
def indicators():
    from pathlib import Path

    from gauge.config import load_study

    root = Path(__file__).resolve().parents[1]
    return load_indicators(load_study("config/study.yaml", root=root))


@pytest.fixture(scope="module")
def patterns(indicators):
    return mention_pattern(indicators)


SHOWN = [
    Shown("emissions_intensity", D("1093")),
    Shown("emissions_intensity", D("866.2")),  # a printed cut-point
    Shown("water_intensity", D("403.6")),
    Shown("renewable_share", D("2.679")),
    Shown("revenue_from_operations", D("75955.1"), CRORE),
    Shown("energy_total", D("357165000")),
]


# ---- extraction ----------------------------------------------------------------------------------
def values(text):
    return [n.value for n in extract_numbers(text)]


def test_numbers_with_separators_decimals_and_percent():
    assert values("Water intensity is 1,093 and 403.6 kL") == [D("1093"), D("403.6")]
    found = extract_numbers("a renewable share of 2.679% against 5%")
    assert [(n.value, n.percent) for n in found] == [(D("2.679"), True), (D("5"), True)]
    assert values("revenue 75,955.1 crore") == [D("75955.1")]


def test_fiscal_years_scope_numbers_and_unit_digits_are_not_claims():
    text = "Scope 1 and 2 emissions in FY2024-25 (2024-25) of tCO2e fell versus FY23"
    assert values(text) == []
    assert values("Scope 1+2 intensity is 1,093") == [D("1093")]
    assert values("CO2 and H2O are not numbers: 12 is") == [D("12")]  # 12 > 10: a claim


def test_small_bare_integers_are_ignored_but_percent_decimals_and_multipliers_count():
    assert values("top 3 drivers, 2 of 5, rank 10") == []
    assert values("a score of 11") == [D("11")]
    assert values("about 0.5 and 7.5") == [D("0.5"), D("7.5")]
    assert values("5% share") == [D("5")]
    assert [(n.value, n.multiplier) for n in extract_numbers("3 million GJ")] == [
        (D("3"), D("1000000"))
    ]


@pytest.mark.parametrize(
    "text, mult",
    [
        ("6.4 million GJ", 10**6),
        ("6.4 mn GJ", 10**6),
        ("6.4 thousand t", 10**3),
        ("6.4k t", 10**3),
        ("6.4 billion INR", 10**9),
        ("75,955 crore", 10**7),
        ("12 lakh", 10**5),
        ("12 lakhs", 10**5),
    ],
)
def test_multiplier_words(text, mult):
    assert extract_numbers(text)[0].multiplier == Decimal(mult)


def test_clauses_split_on_sentence_ends_not_on_decimal_points():
    text = "Water intensity is 403.6. Emissions are high; scope 2 is low! Done"
    assert split_clauses(text) == [
        "Water intensity is 403.6",
        "Emissions are high",
        "scope 2 is low",
        "Done",
    ]


def test_indicator_mentions_use_printed_labels_and_the_unparenthesised_alias(patterns):
    assert mentioned_codes("Emissions intensity (Scope 1+2) is high", patterns) == [
        "emissions_intensity"
    ]
    assert mentioned_codes("emissions intensity is high", patterns) == ["emissions_intensity"]
    assert mentioned_codes("Scope 1 emissions and WATER INTENSITY", patterns) == [
        "scope1_emissions",
        "water_intensity",
    ]
    found = mentioned_codes("Renewable energy share beats renewable energy consumption", patterns)
    assert set(found) == {"renewable_share", "energy_renewable"}
    assert mentioned_codes("nothing relevant", patterns) == []
    assert "emissions_intensity" not in mentioned_codes("Scope 1 emissions only", patterns)


# ---- labelling a number --------------------------------------------------------------------------
def n(value, mult=None, percent=False):
    return ClaimedNumber(str(value), D(str(value)), None if mult is None else D(mult), percent)


@pytest.mark.parametrize(
    "claimed, named, status",
    [
        ("1093", ["emissions_intensity"], "supported"),
        ("1103", ["emissions_intensity"], "supported"),  # 0.91% off: inside the 1% tolerance
        ("1104", ["emissions_intensity"], "wrong"),  # 1.01% off: a misquote
        ("1180", ["emissions_intensity"], "wrong"),  # 8% off: still a misquote of that indicator
        ("1300", ["emissions_intensity"], "unsupported"),  # 19% off: not traceable
        ("403.6", ["emissions_intensity"], "wrong"),  # the water value, attributed to emissions
        ("403.6", ["water_intensity"], "supported"),
        ("866.2", ["emissions_intensity"], "supported"),  # the printed cut-point counts as printed
        ("403.6", [], "supported"),  # no indicator named: any printed value of the company
        ("777", [], "unsupported"),
        ("2.679", ["renewable_share"], "supported"),
    ],
)
def test_number_labels(claimed, named, status):
    assert label_number(n(claimed), named, SHOWN)[0] == status


def test_the_matched_value_is_reported():
    assert label_number(n("1110"), ["emissions_intensity"], SHOWN) == ("wrong", D("1093"))
    assert label_number(n("1093"), ["emissions_intensity"], SHOWN) == ("supported", D("1093"))
    assert label_number(n("777"), [], SHOWN) == ("unsupported", None)


def test_unit_normalisation_of_scaled_claims():
    # revenue is printed in INR crore: "75,955 crore" and "759.55 billion" are the same amount
    revenue = ["revenue_from_operations"]
    assert label_number(n("75955", "10000000"), revenue, SHOWN)[0] == "supported"
    assert label_number(n("759.55", "1000000000"), revenue, SHOWN)[0] == "supported"
    assert label_number(n("75955"), revenue, SHOWN)[0] == "supported"  # read in the printed unit
    assert (
        label_number(n("75955", "1000000"), revenue, SHOWN)[0] != "supported"
    )  # million: wrong scale
    energy = ["energy_total"]
    assert label_number(n("357.2", "1000000"), energy, SHOWN)[0] == "supported"
    assert label_number(n("357165", "1000"), energy, SHOWN)[0] == "supported"
    assert label_number(n("357.2", "1000"), energy, SHOWN)[0] != "supported"


def test_zero_matches_only_zero():
    zero = [Shown("water_intensity", D("0"))]
    assert label_number(n("0.0"), ["water_intensity"], zero)[0] == "supported"
    assert label_number(n("0.5"), ["water_intensity"], zero)[0] != "supported"


# ---- labelling a justification -------------------------------------------------------------------
def test_clauses_become_claims_with_the_worst_status(patterns):
    text = (
        "Water intensity is 403.6 kL per INR crore. Emissions intensity is high; "
        "the sector median fell from 900 last year. Renewable energy share of 2.679% and "
        "Water intensity of 430."
    )
    claims = label_justification(text, patterns, SHOWN)
    by_index = {c.clause_index: c for c in claims}
    assert by_index[0].claim_type == "numeric" and by_index[0].status == "supported"
    assert by_index[0].indicator_code == "water_intensity" and by_index[0].matched_value == D(
        "403.6"
    )
    assert by_index[1].claim_type == "indicator_only" and by_index[1].status == "pending_annotation"
    assert by_index[2].claim_type == "numeric" and by_index[2].status == "unsupported"
    assert by_index[2].indicator_code is None and by_index[2].claimed_value == D("900")
    # the last clause has one supported and one wrong number: the clause takes the worst
    assert by_index[3].status == "wrong" and by_index[3].claimed_value == D("430")


def test_clauses_without_numbers_or_indicators_are_not_claims(patterns):
    assert label_justification("The company looks acceptable overall.", patterns, SHOWN) == []
    assert label_justification("", patterns, SHOWN) == []


# ---- what each prompt showed ---------------------------------------------------------------------
def test_c1_shows_no_trend_or_sector_statistics_but_c2_does(ctx, world):
    ev, rule = ctx.evidence, ctx.rule
    code = sorted(ev.companies)[0]
    ce = ev.companies[code]
    c1 = shown_values(ce, ev, rule, world.ind, "C1")
    c2 = shown_values(ce, ev, rule, world.ind, "C2")
    assert len(c2) > len(c1) and all(s in c2 for s in c1)
    old = ce.trend["emissions_intensity"]["FY2022-23"]
    median = ev.sectors[ce.sector].stats["emissions_intensity"]["median"]
    assert Shown("emissions_intensity", old) in c2
    assert Shown("emissions_intensity", median) in c2
    assert Shown("emissions_intensity", old) not in c1 or old == ce.kpis["emissions_intensity"]
    cut = rule.cut_points[ce.sector]["emissions_intensity"].p33
    assert Shown("emissions_intensity", cut) in c1  # cut-points are printed under both conditions
    revenue = next(s for s in c1 if s.code == "revenue_from_operations")
    assert (
        revenue.unit_factor == CRORE and revenue.value == ce.indicators["revenue_from_operations"]
    )


def test_a_trend_value_quoted_under_c1_is_unsupported_but_supported_under_c2(ctx, world, patterns):
    ev = ctx.evidence
    ce = ev.companies[sorted(ev.companies)[0]]
    old = ce.trend["water_intensity"]["FY2022-23"]
    assert old != ce.kpis["water_intensity"]
    from gauge.render.prompts import num

    text = f"Water intensity was {num(old)} in the first year"
    for condition, expected in (("C1", "unsupported"), ("C2", "supported")):
        shown = shown_values(ce, ev, ctx.rule, world.ind, condition)
        (claim,) = label_justification(text, mention_pattern(world.ind), shown)
        assert claim.status in (expected, "wrong" if expected == "unsupported" else expected)
        if condition == "C2":
            assert claim.status == "supported"


# ---- storing claims ------------------------------------------------------------------------------
def make_judgment(world, ctx):
    plan = render_run_prompts(world.cfg, world.ind, world.models, ctx)[0]
    codes = sorted(ctx.evidence.companies)
    runner = CannedRunner(
        {plan.planned.run_id: [good_item(c, world.ind.driver_labels) for c in codes]}
    )
    with session_scope(world.engine) as s:
        prompt, system = plan.prompt.for_channel("cursor")
        execute_run(s, world.cfg, runner, plan.planned, prompt, system_prompt=system)
    stage_parse(world.engine, world.cfg, world.ind)
    with session_scope(world.engine) as s:
        return s.scalars(select(Judgment.id).order_by(Judgment.id)).first()


def claim(index, text, status="supported", kind="numeric"):
    return ClaimResult(index, text, kind, "water_intensity", D("1"), None, status)


def test_claims_are_upserted_and_annotated_claims_are_protected(world, ctx):
    jid = make_judgment(world, ctx)
    with session_scope(world.engine) as s:
        assert store_claims(s, jid, [claim(0, "A is 11"), claim(1, "B is 12", "wrong")]) == 2
    with session_scope(world.engine) as s:
        first = {
            c.clause_index: c.id for c in s.scalars(select(Claim).where(Claim.judgment_id == jid))
        }
        # the same text again: rows (and so their ids) are kept, the labels are refreshed
        store_claims(s, jid, [claim(0, "A is 11", "unsupported"), claim(1, "B is 12", "wrong")])
    with session_scope(world.engine) as s:
        rows = {c.clause_index: c for c in s.scalars(select(Claim).where(Claim.judgment_id == jid))}
        assert {i: c.id for i, c in rows.items()} == first and rows[0].status == "unsupported"
        s.add(
            Annotation(claim_id=rows[1].id, annotator="A", kind="claim_support", label="supported")
        )
    with (
        session_scope(world.engine) as s,
        pytest.raises(ClaimStoreError, match="has human annotations"),
    ):
        store_claims(s, jid, [claim(0, "A is 11"), claim(1, "B changed text", "wrong")])
    with session_scope(world.engine) as s, pytest.raises(ClaimStoreError):
        store_claims(s, jid, [claim(0, "A is 11")])  # clause 1 would vanish
    with session_scope(world.engine) as s:  # an unannotated claim may be replaced or removed
        store_claims(s, jid, [claim(0, "A is now 13"), claim(1, "B is 12", "wrong")])
        assert s.scalar(select(Claim.clause_text).where(Claim.clause_index == 0)) == "A is now 13"
        assert s.scalar(select(Run.id)) is not None
