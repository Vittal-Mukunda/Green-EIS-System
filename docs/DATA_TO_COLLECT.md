# Data to collect, and which sector (decision 2026-10-26)

The ASI run (see [FINDINGS.md](FINDINGS.md)) calibrates the proxies on thousands of small registered
factories but only for electricity, coal and gas, and only for *reported* quantities. A paper that says
anything about informal units, liquid fuels, or real owners needs the data below. Ranked by what unblocks
the most.

## Sector decision

**Primary sector: textile wet processing (dyeing, printing, finishing), ASI NIC division 13, in one
cluster (Pali, Surat or whichever the owner can reach).** Secondary, optional: coal-fired brick kilns.

Why textile processing, by the criteria a reviewer will apply:

| Criterion | Textile wet processing | Brick kilns | Food (dal mills etc.) |
|---|---|---|---|
| Matters in the published gap | second-largest informal coal user (18% in 2005-06, CEEW); shifted to petroleum coke since | largest single user (about 49% of informal coal in 2015-16) and the most disputed estimate (26 vs 35-69 Mt) | third (16%) |
| Several fuels per unit, so a hotspot ranking means something | **yes**: boiler or thermal-oil heater fuel (coal, lignite, pet coke, wood), grid electricity, diesel generator | **no**: one fuel dominates, the ranking is trivial | mostly electricity |
| Tests the hypotheses H4 and H5 (hotspot stability, priority rule) | yes | barely | barely |
| Data a unit realistically holds (bills, fuel invoices, meter, DG log) | good | weak (fuel often bought in bulk, production in bricks) | good |
| Existing public anchor for cross-checking | BEE/SAMEEKSHA manuals for Pali (24 audits) and Surat (60 detailed audits) exist, though unit annexures were not found | BEE manuals (Varanasi, Ludhiana) | small |
| Already in the ASI calibration set | yes (NIC 13) | yes (NIC 23) | yes (NIC 10) |

**Evidence from our own data (exploratory textile cut, 2026-10-26):** among 1,105 small NIC 13 factories in
ASI, only 100 have two or more fuel items and 5 allow the priority test, and no liquid fuel is usable. The
proxy-error result carries over to textiles, but the hotspot hypotheses (H4, H5) cannot be tested there
without unit data. This is why section C below is the main collection.

Brick kilns are kept as the **motivating case in the introduction** (the disagreement is the clearest
evidence for the gap) and as an optional contrast, not as the main sample. One sector keeps the sample
homogeneous; the paper must still say its results hold only for the cases studied.

This is a judgement from the evidence above, not a result. Override it if the owner can reach units in
another sector with measured data: the study needs access more than it needs this particular sector, and
the rule in [RESEARCH_DESIGN.md](RESEARCH_DESIGN.md) §9 (log any change before looking at results) applies.

Textile processing needs one thing the library lacks: **petroleum coke, lignite and wood factors** (V-23).
Collecting those is item B1 below.

## A. Only you can do these (blocking)

| # | What | Why | Where / how |
|---|---|---|---|
| A1 | Ask the teacher whether small registered factories (ASI) are an acceptable stand-in for informal units, and whether one survey year is enough | Decides whether the ASI result can be the paper's evidence base or only the calibration | Written answer, keep it |
| A2 | Read the microdata.gov.in terms of use and tell us any limit on thesis, publication or sharing | Factory-level rows must not be shared until read (V-18) | Portal, "Policies and Guidelines" |
| A3 | Free login; download Blocks A, E and H of ASI **2022-23 and 2021-22**, `.dta`, unedited | A true held-out-year test of the calibration (V-35) | microdata.gov.in, catalogue 205 and 188 |
| A4 | Confirm which paper's wording is cited for the gap (CSTEP 2018 as assumed, or CEEW 2018) | Both are verified to say it; pick one for the introduction | decision |
| A5 | Confirm AR5 or AR6 warming potentials (V-05) and reading the placeholder range as a 90% interval (V-25) | Needed before calibrated numbers are reported | decision |

## B. Reference data we can fetch ourselves (needs your approval for each download)

| # | What | Use |
|---|---|---|
| B1 | Emission factors, net calorific values and densities for **petroleum coke, lignite, firewood/biomass**, with source and year | Fills V-23 and V-24; needed before any textile unit can be computed. Candidate sources: IPCC 2006 Vol. 2 defaults (not yet read), Indian NCV tables |
| B2 | State electricity tariffs and recent state fuel prices (coal, pet coke, diesel, LPG) for the chosen cluster | Prices for the "Estimated" proxy in the cluster |
| B3 | Wayback copies of the BEE unit audits and the Pali annexure volumes (I-VI) | Possible unit-level measured data without a factory visit (V-08, V-21, V-36). Retry later or from another network; or ask TERI (sameeeksha@teri.res.in) |
| B4 | NIC 13 totals from the ASI file by state | Context table: how big the textile sector is in the calibration sample |

## C. Unit-level data from real units (the main new collection)

Target: **at least 20 units from at least 2 clusters** (the pre-set data gate; placeholder). If that is
unreachable, 5 to 8 units become a clearly labelled case study and the hypotheses are reported descriptively.

For **each unit**, for **each of the last 12 months** (annual totals only if monthly is impossible; say so):

| Field | Detail |
|---|---|
| Unit identity | anonymous id, cluster, NIC code, process type, persons worked, registered or not |
| Production | quantity processed (kg or metres of fabric), operating hours or days per month |
| Grid electricity | kWh and rupees for each month, from the bill; meter reading if the owner reads it |
| Each thermal fuel | boiler or thermal-oil heater fuel: type, quantity with **unit**, rupees, supplier invoice or stock movement; opening and closing stock if kept |
| Diesel / DG set | litres bought, rupees, DG running hours, rated kVA |
| Other fuels | LPG, firewood, anything else, with unit and rupees |
| Equipment | boiler or heater rating and age, DG rating, major motors (kW) |
| **How each number is known** | for every quantity above: *measured* (metered or weighed), *estimated* (derived from spend or hours), or *default* (guessed or none). **Recorded by the owner, not assigned by us.** This is what turns the study from a simulation into a test on real owners |
| **A measured reference** | for as many quantities as possible: meter readings, weighed stock, tanker dip, or an energy auditor's measurement, taken independently of the owner's own estimate |

Rules: no personal or identifying details beyond what the analysis needs; written consent; record how the
data were collected; do not "clean" a number to look consistent. Anything the owner cannot give stays
missing and is counted, not filled.

## D. Optional, small, and worth doing

| # | What | Use |
|---|---|---|
| D1 | A 3-5 person usability check of the data-entry page (can an owner with bills fill it in; do they understand the trust label) | The monthly workflow is otherwise a design feature, not a tested one |
| D2 | One or two interviews or site notes in the cluster about what records a unit actually keeps | Grounds the four data-quality profiles (`bills_only`, `minimal`, `invoices_main`, `random_mix`), which are assumptions today (V-27) |

## What each item unblocks

| Item | Unblocks |
|---|---|
| A1, A2 | Using the ASI results in a paper at all |
| A3 | Held-out-year calibration; removes the "one year" limit |
| B1 | Any textile-unit computation |
| C | The claim that the trust label works for **real owners** and **informal or small units**; liquid-fuel results; a real test of H5 on more than 67 factories |
| D1 | The usability sentence in the paper |

Without C the paper can honestly claim: a calibration of data-class errors on small registered factories
for electricity, coal and LPG, and a design. With C it can claim a test on units and fuels the ASI cannot
reach.
