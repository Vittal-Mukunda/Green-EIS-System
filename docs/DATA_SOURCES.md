# DATA SOURCES

Researched 2026-10-02 (Phase 2). Every claim is tagged **verified** (read in the primary source during
this research), **secondary** (stated by a web summary or third-party page, not checked against the
primary source) or **unverified**. Open items are tracked in `docs/VERIFY.md`.

## Decision

1. **Primary source: BRSR XBRL filings on NSE and BSE**, downloaded **by hand** by the owner into
   `data/raw/` (about 20 companies x 3 years = 60 filings), with the PDF filing for cross-checks.
2. **Fallback and first-class path today: the manual-entry CSV** (`data/manual_entry_template.csv`),
   with a validator, mandatory provenance and strict units. It is implemented and tested.
3. **XBRL loading is built and was run on 20 real filings** (`gauge ingest --xbrl PATH`). The mapping
   (`config/xbrl_mapping.yaml`) was written from the real files and checked against NSE's published
   taxonomy, because element names must not be guessed (hard rule 8). See the next section.
4. **No scraper is built.** NSE's terms restrict automated collection (see Licence).

## What the research verified

| Fact | Status | Source |
|---|---|---|
| BRSR is required for the top 1,000 listed companies by market capitalisation from FY2022-23 (voluntary FY2021-22), submitted in **both PDF and XBRL** | verified | XBRL International / At Quest, *Unearthing Insights from India's ESG Disclosures* (Feb 2024), pp. 2-3; also xbrl.org news "India gears up for digital sustainability reporting" (July 2022) |
| The updated BRSR format applies to the top 1,000 listed entities from **FY2023-24** (SEBI circular 12 July 2023, ref. SEBI/HO/CFD/CFD-SEC-2/P/CIR/2023/122, para 3.4.1) | verified | the circular itself (downloaded, `docs/REFERENCE_FILES.md`) |
| Reasonable assurance of BRSR Core on a glide path: top **150** entities by market capitalisation in FY2023-24, **250** in FY2024-25, **500** in FY2025-26, **1000** in FY2026-27 | verified | same circular, para 3.4.2 |
| Official units in the SEBI BRSR Core annexure: GHG "Mn MT / KT / MT" (CO2e); water "Mn Lt or KL"; energy "In Joules or multiples"; waste "Kg / MT" | verified | SEBI, *Annexure I - Format of BRSR Core* (July 2023), pp. 1-5 |
| Total energy = non-renewable fuel + renewable fuel + purchased and self-generated electricity, heating, cooling, steam (self-generated energy counted once); renewable share = renewable energy / total energy, in % | verified | same annexure, p. 3 |
| BRSR Core water measure is **water consumption** (and its intensity is consumption / revenue), which matches the owner's decision on water intensity (V-05) | verified | same annexure, pp. 2-3 |
| Principle 6 Essential Indicators question numbers. **2023 format** (FY2023-24 on): **Q1** energy, **Q3** water, **Q7** GHG, **Q9** waste. **2021 format** (FY2022-23): Q1 energy, Q3 water, **Q6** GHG, **Q8** waste | verified | the BRSR Core annexure (cross-references) and both SEBI format documents (downloaded) |
| Intensity definitions differ between formats. 2021: "per rupee of turnover (Total energy consumption / turnover in rupees)", water "(Water consumed / turnover)". 2023: "(Total energy consumed / Revenue from operations)", plus PPP-adjusted and physical-output variants, and a new waste intensity. The absolute indicators have the same wording in both | verified | SEBI Annexure I (2021) and Annexure II (2023) |
| Section A: reporting boundary is Q13 in both formats (standalone or consolidated); turnover is stated "in Rs."; assurance provider and type are Q14-15 in the 2023 format only | verified | same two documents |
| BRSR Core intensities are per **revenue from operations adjusted for PPP**; ours are per INR crore, unadjusted (a deliberate, different definition: METHODS.md) | verified | same annexure, pp. 2-4 |
| Real BRSR XBRL data has recurring quality problems: values reported in crore/lakh instead of unscaled; **zeros reported for mandatory metrics** (Scope 2, water withdrawal); **intensity denominators scaled** by the filer; emission units as **free text** ("Metric tonnes of CO2 equivalent", "Metric tonnes of CO2 eq.", "CO2 in MT"); human errors and **PDF/XBRL mismatches** | verified | At Quest / XBRL International paper, section 6 (1,059 FY2022-23 XBRL filings obtained from NSE) |
| NSE's **XBRL Information** page (`https://www.nseindia.com/companies-listing/xbrl-information`) offers a BRSR taxonomy zip (`Taxonomy_BRSR_20260330194931.zip`, 869 KB) and a filers' utility zip (1.36 MB) | verified (viewed in a browser) | NSE page, 2026-10-02 |
| NSE's BRSR filings page (`https://www.nseindia.com/companies-listing/corporate-filings-bussiness-sustainabilitiy-reports`, NSE's own spelling) lists filings with PDF and XBRL download icons, original and latest-revision dates; its date filter is on submission date; 1,270 records at the time | verified (viewed in a browser) | NSE page, 2026-10-02. An earlier URL from a search result was dead |
| BSE shows BRSR under Corporates > Corporate Filings | secondary | search results; not checked |

Still not verified: the taxonomy versions used by filings of FY2023-24 and earlier (see V-18), and
whether BSE's terms of use allow what NSE's do not.

## What the real XBRL files look like (20 FY2025-26 filings, surveyed 2026-10-02)

The owner downloaded one XBRL file for each of the 20 primary companies, plus the BRSR taxonomy zip.
Everything in this section was read from those files, not assumed.

| Finding | Evidence |
|---|---|
| Plain `.xml`, not zipped. All 20 use one taxonomy, `in-capmkt-ent-2026-02-28.xsd` (namespace `https://www.sebi.gov.in/xbrl/2026-02-28/in-capmkt`) | the files |
| Each filing holds the **current year (FY2025-26) and the previous year (FY2024-25)** as company-level facts; contexts have no dimensions and a 12-month April-March period. A third year appears only for a few HR facts | 20 of 20 |
| The company is identified by **ISIN**, a fact in the filing (also name, CIN, reporting boundary, assurance provider). The ISINs match `candidate_pool.csv` exactly | 20 of 20 |
| All nine indicators are present for both years in every filing | 360 of 360 values |
| **All 24 element names the loader uses are defined in the official taxonomy** (`core/in-capmkt.xsd`): nine indicators, identity, assurance, intensity and revenue-anchor elements | `Taxonomy_BRSR_20260330194931.zip`, checked name by name |
| All 20 filings state **Reasonable** assurance for energy, GHG, water and waste, and name the assurer | 20 of 20 |
| Reporting boundary is mixed: **12 standalone, 8 consolidated** (e.g. ITC, Nestle, ACC, Ambuja, Tata Steel, JSW, SAIL, JK Cement, Shree, JSPL, JSL, Godrej standalone; Infosys, TCS, Wipro, HCL, TechM, UltraTech, HUL, Britannia consolidated) | `ReportingBoundary` fact |

### Units and scales are not reliable (and what is done about it)

| Problem | Where | Handling |
|---|---|---|
| `Non-SI:MtCO2e` is **tonnes** for most filers (UltraTech Scope 1 = 88,884,246) but **million tonnes** for Tata Steel (Scope 1 = 64). In the XBRL Unit Type Registry `MtCO2e` means million tonnes, so the filers who tag tonnes are mis-tagging | taxonomy types Scope 1/2 as `ghgEmissionsItemType`; UltraTech's own intensity row reproduces tonnes; Tata Steel's PDF p.48 says "Million tonnes CO2e 64 61" | zero or a value of 1000 or more under that label is read as tonnes (no company emits 1000 Mt); anything below needs an override with evidence |
| `iso4217:INR` revenue is in **rupees** for 18 filers (SAIL for its current year), **crore** for HUL (63,493), **million** for Nestle (230,715), and **thousand** for SAIL's FY2024-25 column (985,697,200) | Section A fields in the same filings (HUL `TotalRevenueOfTheCompany` = 657,250,000,000; Nestle `Turnover` = 230,714,626,515); SAIL's year-over-year ratio of 1/1124 and its PDF's intensity row | a value outside INR 1,000 crore to INR 10 lakh crore is not read as rupees; a hint is printed from Section A; an override with evidence resolves it |
| Energy labels vary by filer: **TJ (5 filers), GJ (12), MJ (3)** | unit measure on each fact | converted exactly |
| Filers scale the **intensity denominator** like the revenue (HUL's "per rupee" intensity is per crore), so the filing's own intensities cannot reveal a scaled revenue; they do confirm the numerator unit | absolute / (intensity x revenue) is within 5% of 1 for every checkable filing, including HUL and Nestle (Tata Steel's GHG intensity is reported as 0, so it cannot be checked) | used only as a numerator-unit check |
| Recovered waste **exceeds** generated waste for 7 company-years (JK Cement, JSL, SAIL, Tata Steel) | Tata Steel's PDF table lists total recovered 1,88,42,244 t, identical to the XBRL | a real property of the filings (recovery from legacy stock), kept and flagged `recovered_le_generated` |
| JSPL renewable energy rose 43-fold (11.2 to 486.6 TJ) | JSPL PDF p.36: "0.4866 0.0112" PJ | real; flagged by the 2-year-change check where it applies |

The four overrides (`config/xbrl_overrides.yaml`) each cite their evidence and are stored with every
affected value as a quality flag. A filing that references any other taxonomy version is **refused**,
because an element name can keep its spelling and change meaning between versions.

## Consequences of the research for the design

- **Strict units.** The documented free-text and scaling errors are why `standardize` rejects units it
  cannot convert exactly (`ton`, `ml`, `MLD`, fused forms like `MtCO2e`, calorie and BTU units) instead
  of guessing, and why the validators flag zeros, negatives and ordering violations. `MT`, `KT` and
  `Mn MT` are read in SEBI's notation (metric tonne, kilotonne, million metric tonnes). Check the
  filing's own unit text for every value you enter.
- **Cross-check every value against the PDF** (`verify-sample`, Phase 3), since PDF and XBRL disagree
  in places.
- **Format change inside the trend window.** FY2022-23 filings use the earlier BRSR format and
  FY2023-24 onward the revised one, so the three-year trend crosses a format change (V-16).
- **Assurance.** BRSR Core assurance starts in FY2023-24 with the top 150 entities and reaches the top
  250 in FY2024-25 (verified: SEBI circular para 3.4.2). FY2022-23 reports are therefore outside the
  mandate, and whether a given report is assured depends on the company's market-cap rank that year.
  `report.assured` records what each filing says; it is a data-quality caveat, not a model input.

## Licence and terms of use

**NSE: read directly in a browser on 2026-10-02** (Terms of Use, updated 29 Oct 2025). The relevant
points: content may not be copied, reproduced, stored, distributed or published without NSE's prior
written permission, "unless the information or Content is available for download"; and "User is
prohibited to conduct any systematic or automated data collection activities (including scraping, data
mining, data extraction and data harvesting) on or in relation to our Website". A separate NSE data
usage policy (seen only in search excerpts) limits its data portal to non-commercial use.

**BSE: not read.** Its terms URL redirects to its homepage and its footer links were not exposed.

What this means here (V-15; **please read the terms yourself before downloading**):

- Download the filings manually, one by one, for personal academic use.
- `data/raw/` is gitignored; do not publish the raw filings or this folder.
- The paper and any repository should publish **derived values with provenance** (company-year,
  indicator, value, unit, page reference), not copies of the filings.
- The filings themselves are public disclosures made by the companies; this is not legal advice.

## Alternatives considered

| Source | Why not |
|---|---|
| Dataful "BRSR_P6" dataset | Scope 1/2/3 emissions only (no energy, water, waste or revenue); access listed as "Exclusive"; licence not stated on the page. Coverage 2019-20 to 2025-26 for the top 1,000 companies |
| GitHub tools for NSE/BSE XBRL (financial-results downloaders, BRSR claim checkers, an AI BRSR filing generator) | not audited; the financial-results one is not about BRSR; automated downloading conflicts with NSE's terms. Listed only as leads |
| Commercial ESG databases | paid; out of budget |

## Our indicators and where they sit in the BRSR

The XBRL element for each indicator (taxonomy 2026-02-28, all checked in the taxonomy and in 20
filings). The BRSR question numbers are from the SEBI formats. `brsr_ref` and `xbrl_element` in
`config/indicators.yaml` are still `TODO(verify)`; the authoritative mapping is `config/xbrl_mapping.yaml`.

| Indicator (our code) | XBRL element | BRSR question |
|---|---|---|
| `revenue_from_operations` | `RevenueFromOperations` (scale varies by filer) | Section A turnover; intensity denominator |
| `energy_total` | `TotalEnergyConsumedFromRenewableAndNonRenewableSources` | P6 Q1 |
| `energy_renewable` | `TotalEnergyConsumedFromRenewableSources` (renewable + non-renewable = total, checked for UltraTech) | P6 Q1 |
| `scope1_emissions`, `scope2_emissions` | `TotalScope1Emissions`, `TotalScope2Emissions` (unit label ambiguous, see above) | P6 Q7 (2023) / Q6 (2021) |
| `water_withdrawal`, `water_consumption` | `TotalVolumeOfWaterWithdrawal`, `TotalVolumeOfWaterConsumption` (kL) | P6 Q3 |
| `waste_generated`, `waste_recovered` | `TotalWasteGenerated`, `TotalWasteRecovered` (t; recovered = recycled + re-used + other, checked for UltraTech) | P6 Q9 (2023) / Q8 (2021) |
| reporting boundary | `ReportingBoundary` ("Standalone basis" / "Consolidated basis") | Section A Q13 |
| assurance | `AssuranceSubTypeFor...` per group (energy, GHG, water, waste) and the assurer's name | per principle |

## Provenance recorded for every filing

File SHA-256, source URL, retrieval date (`report` table), plus `source_url` and `page_ref` for every
value (`indicator_value` table). The manual loader requires `source_url` and `page_ref` on every row
and records the SHA-256 of the CSV itself; pass `--retrieved-on YYYY-MM-DD` to record when you
retrieved the filings (left empty otherwise; it is never guessed).
