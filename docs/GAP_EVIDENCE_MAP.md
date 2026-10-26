# Gap-to-evidence map (2026-10-26)

Where the seven research gaps come from, what supports each, and what is missing. It is the map behind the
Study page, the analysis pages and Overall Findings, which read the same facts from
`src/greeneis/gaps.py` and `src/greeneis/references.py`. Nothing here is a result; results are on the pages.

## The authoritative list

The seven gaps are the rows of **Table 5.1** of
[the reference document](reference/GreenEIS_Research_and_Design_Reference.docx), section 5.1. The earlier
public "Research gaps" page used the same seven, so there was no ambiguity to resolve. Their numbers and
wording were not changed. The research question and hypotheses H1 to H5 are in
[RESEARCH_DESIGN.md](RESEARCH_DESIGN.md); H1 to H3 serve gap 2, H4 and H5 serve gap 3.

**Authoritative data.** The result files in `outputs/` (the main ASI 2023-24 run, the two declared
sensitivity runs, the declared NIC 13 cut) and `outputs/gap_evidence_asi_2023-24.json`. The ASI file itself
(610 MB) is kept outside the project and its portal terms are unread (V-18), so only aggregates are stored.
The CSTEP recomputation and the national estimates come from `src/greeneis/data/` and `greeneis.validation`.

## Map

| Gap | Originating or closest source (how far checked) | Limitation it rests on | Data available | Existing analysis reused | Added here | Not available |
|---|---|---|---|---|---|---|
| 1 No firm-level data | CSTEP 2018 (read), CEEW 2018 (read) | Industry-wise fuel data missing for petroleum and gas and for part of coal; no official energy statistics | ASI 2023-24 small factories | Proxy-error charts (H1 per fuel); case-table funnel | Reporting coverage by fuel line, incl. lines with a spend and no quantity | Informal-unit audits; held-out year; liquid-fuel quantities |
| 2 Uncertainty and conflict | CEEW 2018 (read; own validation vs brick studies); CSTEP 2018 (read); method: GHG Protocol (extract), Kuo 2015 and Weidema 1996 (metadata) | No uncertainty given; totals and brick coal disagree | ASI; national.csv; CSTEP Tables 7 and 8 | H1 to H3 and sensitivity runs; national charts; CSTEP recomputation (43 of 56 agree) | Hypothesis table with Holm p and clusters; sensitivity table | Calibrated ranges; a held-out year; real owners |
| 3 What to fix first | Project reading of CSTEP and CEEW; Halat et al. 2026 (abstract) | National totals only, by design | ASI multi-fuel factories | H4, H5, textile cut | Top-source share, lead, which fuel leads | Many-activity units; liquid fuels; textile units |
| 4 Emissions and cost | CSTEP 2024 (summary page); Helo and Mayanti (abstract, unconfirmed) | Cost and emission objectives can conflict; fuel-price exposure | ASI purchase value and quantity for three fuels | Engine, hotspot cost link (method check) | Spend vs emission shares; INR per tCO2e; biggest cost item vs biggest emitter | Price series; users |
| 5 Reducing without an audit | CSTEP 2024 (summary page), Energetica India (news), Down To Earth (page) | Cluster-level, audit-based evidence | Published factors only | What-if engine, rule library (method check) | kg CO2e per GJ; electrification break-even (hand-checked) | Audited before-and-after data; the CSTEP 2024 report |
| 6 Existing SME tools | SME carbon-tool abstracts and vendor pages (several without authors or year) | Tools demand data, expertise or fees | Factor library | Factor tables | Library inspection; tools table with "not reviewed" | A tool review; users |
| 7 Buyer demands | T20 brief (fragment), Sri Lankan SME abstract | Lost-contract risk | Report generator | Report text checks | Fixed-statement check | Buyer or lender reviews |

## Attribution, stated plainly

- **Verified (gaps 1, 2):** the originating reports were read in the original.
- **Project interpretation (gap 3):** CSTEP and CEEW are national studies by design; the need for a
  unit-level ranking is the project's argument.
- **Unverified (gaps 4 to 7):** only abstracts, summary pages or trade material; the gap is the project's
  synthesis. The pages say "no originating paper could be verified". See V-41 and V-42 in VERIFY.md.

## Statuses

G1 to G4 **partially addressed**; G5 to G7 **insufficient data**; none **addressed with evidence**, because
the only real-data test is on reported (not metered) quantities of registered factories for one year.
