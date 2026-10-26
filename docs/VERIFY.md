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
| V-18 | ASI access terms of use (undertakings, publication limits, sharing) | The 2023-24 file is served publicly and the guidelines call the data freely available, but the portal's policy text is unread; earlier rounds need a free login. Do not share factory-level rows until read | open |
| V-19 | Item-code to fuel mapping for ASI | Resolved for 2022-23: electricity 9990500 (kWh), coal 9990700 (tonne), gas 9990900 (kg); petrol/diesel/oil 9990600 and other fuel 9920400 have no unit and are unusable | confirmed |
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
| V-29 | ASI "Gas consumed" (kg) is LPG or natural gas | **Tested:** the sensitivity run with natural gas gave the same verdicts and near-identical numbers (H4 0.965 vs 0.964); main run reads it as LPG | confirmed (immaterial) |
| V-30 | ASI 2022-23 gives quantity and value only for electricity, coal and gas; liquid fuels are lumped without a unit | Read in the schedule and data structure on 2026-10-25. Limits H4 and H5 to at most three items per factory; state in the paper | confirmed |
| V-31 | ASI rate per unit and small-factory coverage | **Resolved on the real file:** the rate always equals value / quantity (derived, so price proxies are not independent of the factory's own entry); 24,107 / 978 / 1,579 small factories report electricity / coal / gas; 2,442 report two or more | confirmed |
| V-32 | H5 on ASI rests on 67 factories in 16 clusters (98 in 17 in the 100-person run) | Needs two non-measured items; the margin CI nearly touches zero. Report as weak | open |
| V-33 | H3 pooled correlation (-0.97) is largely structural (86,847 of 96,534 profile rows are single-item factories) | Exploratory two-or-more-item result is -0.79; label the first as headline only with the second | open |
| V-34 | The placeholder ranges are miscalibrated per fuel (Default 90th percentile 599% vs 50%; coal and LPG Estimated about 60% vs 25%) | Result of the first real run; calibrate per fuel and validate on a held-out year (needs the owner's login) | open |
| V-35 | One year only (2023-24); clusters are 36 states sharing one year of prices | Earlier rounds need the owner's free login | open |
| V-36 | Wayback BEE reports: file endpoint rate-limited; Pali and Indore unit audits not in the index under their names | Retries refused (429) and stopped; retry later or from another network; see DATA_INVENTORY | open |
| V-37 | ASI portal terms (V-18) read on 2026-10-26 for the public site | The fetch tool rejected the portal's certificate and the in-app browser refused the site; the terms were not read. The public site therefore publishes only the aggregate result files already committed, and no new ASI-derived table | open |
| V-38 | `national.csv`: brick-coal figures of Greentech 2012, CPCB 2015 and MNRE 2013, and CEEW's "coal more than 90%" | Taken from CEEW's own comparison (and the reference document); the original Greentech, CPCB and MNRE reports were not read; marked `cited_by_original`. Read them before quoting in the paper | open |
| V-40 | New ASI aggregates for the research-gap pages: `outputs/gap_evidence_asi_2023-24.json` (counts by fuel line, spend and emission shares, top-source share), produced by `greeneis.study.gap_evidence` | Aggregates only, no factory row, but V-18 (ASI terms unread) and V-37 asked for no new ASI-derived table on the public site. `.gitignore` now allows this one file; **owner to decide before any push** whether it may be published | open |
| V-41 | Citations re-checked on 2026-10-26 (Crossref and publisher pages): Kuo et al. 2015, Halat et al. 2026, Weidema and Wesnaes 1996, Neves-Silva and Camarinha-Matos 2022, Efron 1979, Upadhyay 2022 and CSTEP 2024 page metadata confirmed | Not found or not confirmed: Zocca et al. 2018 (no Crossref match), Helo and Mayanti (a 2026 IEEE EMR article of similar title exists; same work not established), Holm 1979 (metadata written from memory), CEEW web page (HTTP 403). The CSTEP 2024 page names seven clusters but no unit count: the 66 units come from Energetica India (S7). Entries marked in `src/greeneis/references.py` | open |
| V-42 | Gap attributions: gaps 4 to 7 have no verified originating paper; gap 3 is the project's reading of two national studies | See `src/greeneis/gaps.py` (`attribution`). Read CSTEP 2024, the T20 brief and the SME carbon-tool papers in full before the paper says otherwise | open |
| V-43 | Electrification break-even and kg CO2e per GJ on the Gap 5 page use the CEA grid factor (CO2 only) against CSTEP fuel factors with AR5 warming potentials | Factor arithmetic, not a measured result; natural gas CO2 factor is a derived reading (V-02) | open |
| V-39 | Study page and gaps 4 to 7 analysis pages (formerly the Research gaps page): evidence for gaps 4 to 7 (CSTEP 2024 66-unit study, finance needing audits, SME carbon-tool barriers, buyer demands) | Quoted through the reference document (S3, S5, S7, S12 to S15, S20); only S1 and S2 were read in the originals. The page says so | open |
