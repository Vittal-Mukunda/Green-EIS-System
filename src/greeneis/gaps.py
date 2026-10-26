"""The one registry of the project's research gaps.

The seven gaps are the rows of Table 5.1 of the project reference document
(`docs/reference/GreenEIS_Research_and_Design_Reference.docx`, section 5.1); their numbers and titles are
not changed here. The Study page, the analysis pages, the sidebar and the Overall Findings page are all
generated from this list, so an identifier, title or status is written once.

This file holds only text that does not depend on the data. Every number shown to a visitor is read from
the result files or the factor library at run time (see `dashboard/gap_data.py`); nothing computed is
typed in here. Citations are keys into `references.py`.

How a source relates to a gap (`Source.role`):

- ``originating``: the paper that raises the problem or states the limitation the gap rests on.
- ``independent``: a paper that independently reaches a related limitation.
- ``supporting``: literature that supports a design choice or a related claim, not the gap itself.
- ``method``: the basis of a method GreenEIS uses.

``attribution`` says how firmly the gap can be traced to its sources. It is deliberately modest: for gaps
4 to 7 the register holds only abstracts and trade material, so the gap is the project's own synthesis
and is labelled as such.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from . import references

STATUSES: Final = {
    "addressed": "Addressed with evidence",
    "partial": "Partially addressed",
    "unresolved": "Investigated but unresolved",
    "insufficient": "Insufficient data",
}

ROLES: Final = {
    "originating": "Originating study",
    "independent": "Independent study",
    "supporting": "Supporting study",
    "method": "Method basis",
}

ATTRIBUTION_LEVELS: Final = {
    "verified": "Verified: the originating papers were read and state the limitation",
    "interpretation": "Project interpretation: the papers are national in scope; the limitation is our "
    "reading, not their statement",
    "unverified": "Unverified: the sources were seen as abstracts or trade material only",
}


@dataclass(frozen=True)
class Source:
    ref: str
    role: str

    def __post_init__(self) -> None:
        references.get(self.ref)  # an unknown key fails at import, not on a page
        if self.role not in ROLES:
            raise ValueError(f"unknown role {self.role!r}")


@dataclass(frozen=True)
class Gap:
    number: int
    short: str  # sidebar and table label
    title: str  # Table 5.1 wording
    question: str
    sources: tuple[Source, ...]
    attribution: str
    attribution_note: str
    studied: str
    found: str
    gap_simple: str
    gap_academic: str
    why_matters: str
    greeneis_does: str
    evidence: str
    status: str
    status_reason: str
    limits: tuple[str, ...]
    missing: str

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"gap {self.number}: unknown status {self.status!r}")
        if self.attribution not in ATTRIBUTION_LEVELS:
            raise ValueError(f"gap {self.number}: unknown attribution {self.attribution!r}")

    @property
    def id(self) -> str:
        return f"G{self.number}"

    @property
    def nav_label(self) -> str:
        return f"Gap {self.number} · {self.short}"

    @property
    def slug(self) -> str:
        return f"gap-{self.number}"

    @property
    def status_text(self) -> str:
        return STATUSES[self.status]

    def originating(self) -> tuple[references.Reference, ...]:
        return tuple(references.get(s.ref) for s in self.sources if s.role == "originating")


GAPS: Final[tuple[Gap, ...]] = (
    Gap(
        number=1,
        short="Firm-level data",
        title="No firm-level, regularly updated fuel and energy data for informal units",
        question=(
            "How much of what a small factory pays for energy can be turned into a fuel quantity, and "
            "how close does a quantity worked out from a bill come to the quantity the factory reports?"
        ),
        sources=(Source("cstep2018", "originating"), Source("ceew2018", "independent")),
        attribution="verified",
        attribution_note=(
            "Both reports were read in the original. CSTEP says industry-wise data are not public for "
            "petroleum products and gas and exist for only part of coal, and recommends a transparent "
            "monitoring system that records industry-wise fuel use. CEEW says there are no official "
            "energy statistics for the unorganised sector and asks for annual data collection with "
            "better validation (reference document, sections 3.1 and 3.2)."
        ),
        studied=(
            "CSTEP estimated emissions from fossil-fuel use in India's informal sector for 2008-09 to "
            "2015-16 from national fuel supply, following IPCC guidelines. CEEW estimated emissions of "
            "the informal manufacturing industry for 2005-06 to 2015-16 with an indirect labour-input "
            "method, because no official fuel data exist for the sector."
        ),
        found=(
            "Both produced national totals (CSTEP 110 and CEEW 105 MtCO2e for 2015-16; see the Gap 2 page). "
            "Both name the missing input: CSTEP reports that industry-wise fuel data are available for "
            "only part of coal and not at all for petroleum products and gas, and CEEW that there is no "
            "official energy statistics series for these units."
        ),
        gap_simple=(
            "Imagine you want to know how much juice a whole school drinks, but nobody writes down what "
            "each class drinks. All you can do is guess from how many boxes the shop sold. GreenEIS asks "
            "each class to write down its own juice boxes, and to say how sure it is of each count."
        ),
        gap_academic=(
            "Estimates for the informal sector are built top-down from fuel supply or from survey "
            "expenditure, because no firm-level, regularly collected fuel record exists. There is "
            "therefore no ground truth against which a unit's own bill-based estimate can be checked, and "
            "no evidence on how much of a small unit's energy spend can be converted into a quantity at "
            "all."
        ),
        why_matters=(
            "Without unit-level quantities, national inventories cannot be validated from below, and a "
            "unit cannot be told where it stands. Policy that targets fuels (coal in kilns, furnace oil in "
            "boilers) rests on totals nobody can check."
        ),
        greeneis_does=(
            "A monthly entry of quantities and bills per fuel, each line labelled Measured, Estimated or "
            "Default. To test what such records can support without a factory audit, the project uses the "
            "public ASI 2023-24 returns of small registered factories as a stand-in: it counts what they "
            "report, then works each quantity out from spend and compares it with the reported quantity."
        ),
        evidence=(
            "ASI 2023-24 unit-level file (reported, not metered; registered factories, not informal "
            "units; one year). Coverage by fuel line is counted from it, and the proxy errors come from "
            "the pre-specified study run."
        ),
        status="partial",
        status_reason=(
            "The data-entry tool exists and ASI shows what is recoverable from bills, but no real "
            "unit-level audit has been obtained and no informal unit has used the tool. The ASI returns "
            "are a stand-in, so the gap itself, the absence of informal-unit data, remains."
        ),
        limits=(
            "ASI covers registered factories, not informal units.",
            "The reference quantity is what the factory reported, not a metered value.",
            "Only electricity, coal and gas carry a quantity; diesel, furnace oil and other fuels do not.",
            "One year (2023-24); earlier rounds need a free login that has not been created.",
        ),
        missing=(
            "Unit-level energy audits or bills with metered quantities for informal manufacturing "
            "clusters (see docs/DATA_TO_COLLECT.md); ASI 2022-23 and 2021-22 for a held-out year."
        ),
    ),
    Gap(
        number=2,
        short="Uncertainty and conflict",
        title="Estimates carry unquantified uncertainty and numbers conflict across studies",
        question=(
            "Do the Measured, Estimated and Default labels predict how wrong a number is, and are the "
            "uncertainty ranges first assumed for them the right size?"
        ),
        sources=(
            Source("ceew2018", "originating"),
            Source("cstep2018", "independent"),
            Source("ghgp_uncertainty", "method"),
            Source("kuo2015", "method"),
            Source("weidema1996", "method"),
        ),
        attribution="verified",
        attribution_note=(
            "CEEW tested its own method on brick-kiln coal and reported that its figure was far below "
            "other studies, and traced part of the gap to under-counted workers. Neither report gives an "
            "uncertainty range for its national total (reading of the two reports in the project notes). "
            "The pedigree-matrix idea comes from the data-quality-indicator literature "
            "(Weidema and Wesnaes 1996; Kuo et al. 2015) and the GHG Protocol guidance; those papers do "
            "not state this gap, they supply the method."
        ),
        studied=(
            "CEEW checked its demand-side estimate against supply-side and bottom-up studies for brick "
            "kilns. CSTEP reported its fuel-supply estimate with the factors and tables behind it."
        ),
        found=(
            "Two national totals for 2015-16 that are close to each other but built on different data, "
            "and a brick-kiln coal figure from CEEW far below the other studies it cites. Neither gives "
            "a confidence interval."
        ),
        gap_simple=(
            "Two people count the marbles in a jar and say 110 and 105. Neither says how sure they are. "
            "Then you find that for one small bag of marbles the two counts differ a lot. GreenEIS puts a "
            "sticker on every number: counted, worked out, or guessed."
        ),
        gap_academic=(
            "Published informal-sector estimates give point values with no reliability measure, and they "
            "disagree where independent checks exist. Data-quality-indicator schemes can convert a "
            "source label into an uncertainty, but the values used for such conversions are rarely tested "
            "against realised error, in particular for fuel data of small units."
        ),
        why_matters=(
            "A manager, lender or buyer cannot tell a solid figure from a guess, and a label that sounds "
            "scientific but is not tested can mislead. If the assumed ranges are wrong, so is every "
            "interval printed on the report."
        ),
        greeneis_does=(
            "A trust label per number (Measured 1.0, Estimated 0.6, Default 0.3) and an indicative "
            "uncertainty (5%, 25%, 50%), rolled up into a trust index. These values are uncalibrated "
            "design choices. The study tests them against what real small factories reported, and the "
            "project recomputes CSTEP's own petroleum table to see whether the published figures agree "
            "with the published factors."
        ),
        evidence=(
            "The pre-specified study run on ASI 2023-24 (hypotheses H1 to H3), its two declared "
            "sensitivity runs and the declared textile cut; the published national estimates; the "
            "recomputation of 56 cells of CSTEP Table 8."
        ),
        status="partial",
        status_reason=(
            "Best evidenced of the seven: the labels order the error as expected and the placeholder "
            "ranges are shown to be wrong. But the test is on reported (not metered) quantities of "
            "registered factories, the pooled result is mostly electricity, the proxies are applied by "
            "us rather than by owners, and the national conflict itself is not resolved."
        ),
        limits=(
            "Pooled figures are dominated by electricity.",
            "The trust index correlation is largely structural (most factories have one fuel).",
            "The profiles are our assumptions about what a unit records.",
            "The placeholder range is read as a 90% interval, a reading not yet confirmed (V-25).",
            "The cause of the CSTEP table disagreements is unknown; the authors were not contacted.",
        ),
        missing=(
            "A held-out year to test per-fuel ranges; liquid-fuel quantities; real unit audits for a "
            "test with owners' own record-keeping."
        ),
    ),
    Gap(
        number=3,
        short="What to fix first",
        title="National studies do not tell a single factory what to fix first",
        question=(
            "When a unit knows its fuels only roughly, does its largest source of emissions stay the "
            "largest, and does improving the data of the largest source first reduce error most?"
        ),
        sources=(
            Source("cstep2018", "independent"),
            Source("ceew2018", "independent"),
            Source("halat2026", "supporting"),
        ),
        attribution="interpretation",
        attribution_note=(
            "Neither national report states this as a limitation: they report national and sectoral "
            "totals by design. That a single factory needs a ranking of its own sources is the project's "
            "argument. Halat et al. (2026) is cited, from its abstract only, for the point that hotspots "
            "can still be found with approximate data."
        ),
        studied=(
            "The national studies estimated totals by fuel and by industry. Halat et al. studied how "
            "manufacturing SMEs can assess Scope 3 emissions and found that limited supplier data hinder "
            "accuracy while hotspots can still be identified (abstract)."
        ),
        found=("National totals by fuel and sector, with no breakdown for a single factory."),
        gap_simple=(
            "A map of the whole country tells you which cities are big, but not which room in your house "
            "is the messiest. A hotspot list is a tidy-up list for your own house: start with the biggest "
            "mess, but check that you have not misjudged it."
        ),
        gap_academic=(
            "National inventories have no unit-level resolution, and it is untested whether a ranking of "
            "a unit's emission sources survives the data-quality problems that small units have, or "
            "whether directing data improvement to the largest source is better than other rules."
        ),
        why_matters=(
            "A small unit has little money and time. Chasing the wrong source, or improving data nobody "
            "needs, wastes both."
        ),
        greeneis_does=(
            "A Pareto ranking of a unit's activities (the vital few that make up 80% of emissions), with "
            "the cost link beside it. The study tests ranking stability under degraded data (H4) and "
            "the rule 'improve the largest source first' against two alternatives (H5)."
        ),
        evidence=(
            "ASI 2023-24 small factories with two or more tracked fuels; the H4 and H5 results; the "
            "share and lead of the top source in each such factory."
        ),
        status="partial",
        status_reason=(
            "The top source usually stays on top, but a factory here has at most three sources, which "
            "makes the test easy. The priority rule (H5) rests on only a few dozen factories, and for "
            "textiles the test cannot be run at all. Nothing is shown for liquid fuels."
        ),
        limits=(
            "At most three tracked sources per factory (electricity, coal, gas).",
            "H5 rests on a small number of factories and its interval nearly touches zero.",
            "The thin-lead threshold of 10 points is a placeholder (V-26).",
        ),
        missing=(
            "Unit-level data with many activities and liquid fuels (docs/DATA_TO_COLLECT.md section C), "
            "especially for textile wet processing."
        ),
    ),
    Gap(
        number=4,
        short="Emissions and cost",
        title=(
            "Emissions are not linked to cost, but energy is a large share of MSME cost "
            "and prices are volatile"
        ),
        question=(
            "Do the activities that cost the most also emit the most, and how many rupees does a unit "
            "pay per tonne of CO2e for each fuel?"
        ),
        sources=(Source("cstep2024", "supporting"), Source("helo2024", "supporting")),
        attribution="unverified",
        attribution_note=(
            "The reference document cites CSTEP (2024) for MSME exposure to fuel-price rises (summary "
            "page only) and Helo and Mayanti for cost and emission objectives that can conflict "
            "(abstract only, title and venue unconfirmed). No source in the register states this as a "
            "gap for Indian small manufacturing; the gap is the project's synthesis."
        ),
        studied=(
            "CSTEP's 2024 scoping study assessed the technical and financial feasibility of "
            "decarbonisation technologies in seven MSME clusters. Helo and Mayanti studied how energy "
            "cost and emission objectives can move apart under varying grid prices (abstract)."
        ),
        found=(
            "Per the summaries in the reference document: combined measures could cut cost in most "
            "clusters but not all, and cost and emission objectives can conflict. Neither was read in "
            "full."
        ),
        gap_simple=(
            "If you only look at how loud each toy is, you may throw away a cheap toy and keep an "
            "expensive loud one. You need to see the price tag and the noise together."
        ),
        gap_academic=(
            "Emission accounts and cost accounts are kept apart, so a unit cannot see which activities "
            "are costly but low-emission, polluting but cheap, or both. Whether a cost-emission view "
            "changes which activity looks like the priority is not shown for small Indian units."
        ),
        why_matters=(
            "Small units act on cost first. If emission advice ignores cost, it will not be followed; "
            "if it is cost-only, it can steer toward cheap, polluting fuels."
        ),
        greeneis_does=(
            "A cost link: rupees and emissions per activity side by side, with a reading (costly and "
            "polluting; polluting but cheap; costly but low in emissions)."
        ),
        evidence=(
            "Reported spend and calculated emissions for each fuel of ASI 2023-24 small factories; the "
            "share of factories where the biggest cost item is not the biggest emitter."
        ),
        status="partial",
        status_reason=(
            "The cost link can be computed for real reported spend, and it shows that spend and "
            "emissions do not line up fuel by fuel. Whether a unit decides differently because of it, "
            "and the effect of price volatility, are not tested."
        ),
        limits=(
            "Spend is as reported in a return; prices are the factory's average, not a market price.",
            "Only electricity, coal and gas carry both a quantity and a value.",
            "No price series: volatility is not analysed.",
        ),
        missing=(
            "Monthly bills over time (price volatility) and a test with real users; the full text of the "
            "two cited sources."
        ),
    ),
    Gap(
        number=5,
        short="Reducing without an audit",
        title="Decarbonisation evidence is cluster-level and requires audits and engineers",
        question=(
            "Can a manager see what a change in fuel or electricity use would do to emissions and cost "
            "without an audit, and are the suggested actions backed by a source?"
        ),
        sources=(
            Source("cstep2024", "originating"),
            Source("energetica2024", "supporting"),
            Source("dte2022", "supporting"),
            Source("zocca2018", "supporting"),
            Source("nist7850", "supporting"),
        ),
        attribution="unverified",
        attribution_note=(
            "CSTEP (2024) is a cluster-level study, but its report PDF was not read: the page states "
            "seven clusters and not a unit count, and the figure of 66 units over two years comes from "
            "trade-press coverage. That finance often needs audit reports comes from a news article. The "
            "statement that this makes the evidence unusable for a small unit is the project's reading."
        ),
        studied=(
            "CSTEP (2024) assessed deep decarbonisation options in seven clusters (summary page). The "
            "article by Upadhyay (2022) argues that conventional finance will not decarbonise MSMEs."
        ),
        found=(
            "Per the summaries: efficiency, electrification and cleaner-fuel options differ by cluster; "
            "efficiency alone is judged insufficient for deep decarbonisation; some options fail on "
            "capital cost."
        ),
        gap_simple=(
            "A doctor's report about a whole town does not tell you what to eat for dinner. GreenEIS lets "
            "you try 'what if I eat a little less sweets' on your own plate, and says clearly it is a try, "
            "not a prescription."
        ),
        gap_academic=(
            "Decarbonisation evidence comes from audit-based cluster studies that small units cannot "
            "repeat. A lightweight scenario tool exists in the literature for other settings "
            "(Zocca et al.; NIST IR 7850, both unverified), but its use for Indian MSME fuel data, with "
            "stated cautions, is not shown."
        ),
        why_matters=(
            "If only audited units can see their options, most small units cannot plan. If a simple "
            "tool overstates savings, it could mislead investment."
        ),
        greeneis_does=(
            "A what-if simulator (change an activity, switch a fuel, shift electricity) and a rule "
            "library of actions with sources and cautions, all arithmetic on the unit's own numbers."
        ),
        evidence=(
            "The published fuel factors, which fix what any fuel switch can achieve per unit of energy; "
            "the rule library with its sources; the hand-worked reference scenarios that verify the "
            "arithmetic."
        ),
        status="insufficient",
        status_reason=(
            "The simulator is verified against hand calculations, which shows the arithmetic is right, "
            "not that the savings are real. There are no audited before-and-after figures to test it "
            "against, and no unit has used it."
        ),
        limits=(
            "Savings are arithmetic on the entered numbers, not audited results.",
            "Rule-library actions are drawn from cluster studies read through summaries.",
            "Fuels such as pet coke and biomass are not in the factor library (V-23).",
        ),
        missing=(
            "Audited before-and-after energy data for a switch or an efficiency measure; the CSTEP 2024 "
            "report itself; a test with real units."
        ),
    ),
    Gap(
        number=6,
        short="Existing SME tools",
        title=(
            "SME carbon tools exist but demand data, expertise or fees, and few are "
            "India- and MSME-fuel-specific"
        ),
        question=(
            "What does GreenEIS build in that the tools named in the literature are said to lack, and "
            "can that be shown?"
        ),
        sources=(
            Source("digital_reporting", "supporting"),
            Source("ai_reporting", "supporting"),
            Source("srilanka2024", "supporting"),
            Source("ecovadis_estimator", "supporting"),
            Source("persefoni_sme", "supporting"),
            Source("zocca2018", "supporting"),
        ),
        attribution="unverified",
        attribution_note=(
            "The register holds abstracts and vendor pages only; authors and years are missing for "
            "several. Commercial data-quality tools, SME scenario tools and Indian MSME calculators "
            "exist, and the project's search for a tool that combines a per-number trust label, a cost "
            "link and a what-if was partial (V-15). The page therefore says 'we found no tool that "
            "combines all three', not 'first'."
        ),
        studied=(
            "Studies of SME carbon accounting list barriers: expertise, tools, data, cost and low "
            "adoption outside exporters (abstracts)."
        ),
        found=(
            "Barriers are consistently reported; commercial estimator tools are aimed at SMEs but are "
            "generic (vendor material, illustrative only)."
        ),
        gap_simple=(
            "Some shops sell fancy rulers, but they cost money, need a teacher, and are marked in inches "
            "when your cloth is measured in a local unit. GreenEIS is a free ruler marked in your own "
            "units, and it shows where every mark came from."
        ),
        gap_academic=(
            "Tools exist, but for informal Indian manufacturing the barriers are data, expertise and "
            "fees, and generic tools do not carry Indian fuel factors with stated sources and data "
            "quality labels. The claim has not been tested by a systematic tool review or by users."
        ),
        why_matters=(
            "A tool that a small unit cannot afford, cannot feed with data it has, or cannot trust "
            "will not be used, and the sector stays unmeasured."
        ),
        greeneis_does=(
            "Indian fuel and grid factors built in with value, unit, source and year shown; a minimal "
            "input list; no fees; every formula visible."
        ),
        evidence=(
            "The factor library itself: how many factors it holds, from which sources, and how many are "
            "verified in the source document. Nothing is available on how other tools compare."
        ),
        status="insufficient",
        status_reason=(
            "The factor library can be inspected, but the claim about other tools rests on abstracts "
            "and vendor pages, no systematic review was done, and no user has tried GreenEIS. The gap "
            "cannot be evaluated with the evidence in hand."
        ),
        limits=(
            "No feature-by-feature review of any named tool.",
            "Several cited sources have no established authors or year.",
            "Pet coke, biomass, biodiesel and bio-CNG factors are missing (V-23).",
        ),
        missing=(
            "A documented tool review (price, inputs, Indian factors, uncertainty handling) and a "
            "usability check with small-unit managers (docs/USABILITY_AND_BUYER_CHECK.md, not yet run)."
        ),
    ),
    Gap(
        number=7,
        short="Buyer demands",
        title="Suppliers face growing buyer demands for emission data but lack the means to respond",
        question=(
            "Does the one-page report give a buyer or lender what it needs, with the method and its "
            "limits stated?"
        ),
        sources=(
            Source("t20_brief", "supporting"),
            Source("srilanka2024", "supporting"),
            Source("refdoc", "supporting"),
        ),
        attribution="unverified",
        attribution_note=(
            "The lost-contract argument comes from a fragmentary extract of a policy brief whose title "
            "is not established, and from the project's own note. The Sri Lankan SME abstract says "
            "exporters adopt carbon accounting more, which is consistent but is not evidence from "
            "India. No originating paper is verified."
        ),
        studied=(
            "A policy brief argues that SMEs without carbon-accounting capability risk losing contracts "
            "(extract). A conference abstract reports that exporters adopt carbon accounting more "
            "because of external pressure."
        ),
        found=("A plausible but unverified link between buyer pressure and supplier capability."),
        gap_simple=(
            "A big shop asks every small bakery, 'show me how much flour you waste.' A small bakery with "
            "no notebook cannot answer and may lose the order. GreenEIS gives the bakery a one-page "
            "answer, and writes on it that it is an estimate."
        ),
        gap_academic=(
            "Buyer and lender requests for emission data are said to outrun small suppliers' capacity. "
            "Whether a short, labelled estimate is accepted by such buyers is untested."
        ),
        why_matters=(
            "Lost orders and lost finance are the practical cost of having no answer; a misleading "
            "answer, presented as certified, is a different cost."
        ),
        greeneis_does=(
            "A one-page Markdown report with the total, trust index, hotspots, cost link and a standing "
            "statement that it is an estimate and not a certification."
        ),
        evidence=(
            "The report generator's fixed statements, checked by tests. No buyer or lender has "
            "reviewed a report."
        ),
        status="insufficient",
        status_reason=(
            "The report exists and states its limits, but there is no evidence about what buyers accept: "
            "the review protocol has been written and not run, and the supporting sources are "
            "unverified."
        ),
        limits=(
            "No buyer or lender review.",
            "The originating source of the demand claim is not verified.",
        ),
        missing=(
            "Buyer and lender reviews of a report (docs/USABILITY_AND_BUYER_CHECK.md); the original "
            "policy brief."
        ),
    ),
)

_BY_NUMBER = {g.number: g for g in GAPS}


def get(number: int) -> Gap:
    return _BY_NUMBER[number]


def by_slug(slug: str) -> Gap | None:
    return next((g for g in GAPS if g.slug == slug), None)
