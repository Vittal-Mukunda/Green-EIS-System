# Unverified items register

Anything guessed, inherited from a secondary source, or not yet checked against its original. Update
whenever something is assumed. Status: open / confirmed / dropped.

| ID | Item | Why open | Status |
|---|---|---|---|
| V-01 | CEA grid emission factor (0.727 weighted average, 0.757 combined margin tCO2/MWh, FY 2023-24) | **Confirmed 2026-10-25** against CEA CO2 Baseline Database User Guide v20.0 (Dec 2024), Table S, read directly from the PDF (average 0.727 and CM 0.757 adjusted for cross-border transfers; 0.729 and 0.758 without). A secondary source mentions a provisional 0.710 for FY 2024-25 in v21, unchecked; add a row when a newer version is needed | confirmed |
| V-02 | Natural-gas CO2 factor (CSTEP prints "56.100") and volumetric NCV | Decimal-point slip; NCV given per kt but gas needs TJ per volume | open |
| V-03 | Fuel densities (diesel 0.85 kg/L, LPG, others) | ref §7 assumption, no source | open |
| V-04 | Default coal grade (sub-bituminous, CSTEP) | CSTEP applies it to all coal because grade is unknown | open |
| V-05 | GWP set: AR5 (CH4 28, N2O 265) vs AR6 | AR5 chosen to reproduce CSTEP; owner to confirm | open |
| V-06 | CSTEP furnace-oil emissions 2012-13 onward ≈ 9-16% of recomputed | Confirmed in the published Tables 7 and 8 (2026-10-25) and by the engine (validation.py); cause (reclassification, entry error or adjustment) unknown, authors not contacted | open |
| V-07 | CSTEP factor tables labelled "kt/TJ" but magnitudes are kg/TJ | Derived reading, consistent with CEEW's quoted range | open |
| V-08 | Availability of unit-level BEE audit reports | Nine sampled BEE PDF URLs return the homepage (2026-10-25); archive.org returns 429 from this machine; see DATA_INVENTORY.md | open |
| V-09 | Pali cluster manual "24 unit audits in annexure volumes I-VI" | Single search snippet; nothing on sameeeksha.org's listing matches it | open |
| V-16 | Whether BEE audit "measured" values are metered or auditor estimates | Reports not read; index shows only headings | open |
| V-17 | Terms of use of SAMEEKSHA documents | No terms, licence or reuse statement on the site | open |
| V-18 | ASI unit-level data: fuel quantity per item in recent rounds; access terms | Catalog entries exist for 2011-12 to 2023-24 with data-structure and code-list documents; item-level quantity in recent rounds not yet read; portal rejects certificate from this machine; one library guide says free download (dated) | open |
| V-19 | Item-code to fuel mapping for ASI | Needs the round's code list; "other fuels" and coal grade unmapped | open |
| V-20 | CEEW (2017) use of ASI unit-level data (Tier III) | Seen only in a search summary of a slide deck | open |
| V-21 | Annexure Volumes I-VI of the Pali manual (24 audits) exist online | Referenced in the manual; location unknown | open |
| V-10 | Pali DPR Table 1.1 units (electricity 51.3 "MWh/year" for a cluster whose single units use 100-300 MWh per month) | Looks like a unit or scale slip; not checked against the original table | open |
| V-11 | Trust scores 1.0 / 0.6 / 0.3 and ranges ±5 / 25 / 50% | Uncalibrated placeholders (ref §6.5); H2 tests them | open |
| V-12 | Root-sum-square assumes independent errors | Errors from one proxy (e.g. one price) are correlated | open |
| V-13 | ref S12, S13, S14, S15, S18, S20, S21: abstract-only retrieval | Read originals before quoting | open |
| V-14 | ref S11 first author | Corrected: Halat, Childe, Golding, Summerscales (CSR&EM 2026, doi 10.1002/csr.70489), not "Childe et al." | confirmed |
| V-15 | Claim "no tool combines trust score, cost link and what-if" | Search was partial (Semantic Scholar and Google Scholar returned nothing); say "we found no", never "first" | open |
| V-22 | CSTEP Table 8: naphtha disagrees with the report's own factors in all 8 years (ratio published/recomputed 0.87-2.64) and LPG in 2015-16 (0.22 vs 0.18) | Found by recomputing all 56 cells (43 match, 13 flagged). Not in the reference document. Cause unknown (different naphtha quantity or factor?) | open |
| V-23 | Fuels missing from the factor library: pet coke, firewood and other biomass, biodiesel, bio-CNG | Pali's cluster burns pet coke, lignite and wood; needs an Indian source with NCV and factors. IPCC defaults exist but were not read, so none are entered | open |
| V-24 | Fuel densities beyond diesel; volumetric natural gas | Only diesel has a density (assumed, V-03); litres of other fuels and cubic metres of gas are refused | open |
| V-25 | Interpretation of the placeholder uncertainty as a nominal 90% interval (needed by H2) | Design decision pending (RESEARCH_DESIGN §9, item 4) | open |
| V-26 | Study proxies: spend / typical price and sector intensity x scale, leave-one-out with at least 4 other units; thin-lead threshold 10 pp; coverage band 80-95%; q90 factor 1.5 | Placeholders fixed in code before any real data; not tuned | open |
| V-27 | Study profiles (bills_only, minimal, invoices_main, random_mix 0.4/0.4/0.2) are assumptions about record-keeping, not observations | State in the paper | open |
| V-28 | Item-code mapping from the real data source (ASI or BEE) to library fuels | Not written; needs the source's code list (V-19) | open |
