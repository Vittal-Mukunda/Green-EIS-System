# Findings so far (consolidated 2026-10-26)

One page for the owner and the teacher: what was established, from what, how sure we are, and what is
still open. Details live in the linked documents; item ids (V-nn) point to [VERIFY.md](VERIFY.md).
Nothing here is a certified or audited emission figure, and nothing is generalised beyond the cases
studied.

## 1. The gap, checked against the original papers (read 2026-10-26)

| Claim | Evidence | Status |
|---|---|---|
| National estimates for the informal sector disagree | CSTEP 2018 estimates 110 MtCO2e; CEEW 2018 estimates 105 MtCO2e for 2015-16 | read in the PDFs |
| Brick kilns show the disagreement most clearly | CEEW: 26 Mt coal in 2015-16, about 49% of all unorganised-sector coal. Other studies cited by CEEW: Greentech 2012 about 35 Mt; CPCB 2015 35-40 Mt; MNRE 2013 46-69.1 Mt | read in the CEEW PDF |
| Both papers call for firm-level fuel data | CSTEP asks for "a transparent monitoring system to record fuel consumption by various industries in the informal sector"; CEEW says the variation across brick estimates "highlight[s] the data gaps" | read in the PDFs |
| Textile finishing and dyeing is a top coal user | CEEW, 2005-06: non-metallic minerals (mostly bricks) 22%, textile finishing/dyeing 18%, food 16% of informal coal. By 2015-16 dyeing units had moved from coal toward petroleum coke (Faridabad interviews) | read in the CEEW PDF |
| No tool combines a per-number trust label, a rupee link and a what-if, validated | Partial search only (V-15). Pedigree matrices (Weidema, ecoinvent), commercial data-quality tools, SME scenario tools (Zocca et al. 2018) and Indian MSME calculators exist | open: say "we found no tool that combines all three", never "first" |

## 2. What was built (all tested, 141 tests pass, ruff clean)

Factor library (value, unit, source, year for every factor), a Decimal emission engine, trust index and
uncertainty, hotspots with a cost link, a what-if simulator, a recommendation rule library, a one-page
report, a five-hypothesis study harness and an eight-page Streamlit dashboard.

- **Engine checks:** reproduces the reference document's worked example by hand (38.97 tCO2e, trust index
  0.72, +/-12.9%) and the CEA grid factor (0.727 tCO2/MWh average, FY 2023-24, CEA v20.0, V-01).
- **CSTEP Table 8 recomputed, all 56 cells:** 43 match, **13 are flagged, not corrected**: furnace oil
  2012-13 onward (published about 9-16% of the recomputed value), naphtha in all eight years, LPG 2015-16.
  The cause is unknown and the authors have not been contacted (V-06, V-22). CSTEP's factor tables print
  "kt/TJ" where the magnitudes are kg/TJ (V-07).

## 3. Data availability

| Route | Result |
|---|---|
| BEE unit energy audits (Pali, Indore, Ludhiana) | Files removed from the live BEE site; the Wayback copies answered HTTP 429 to every request (V-08, V-36). Not obtained |
| SAMEEKSHA cluster profiles (6 files downloaded) | Cluster and "typical unit" values only, no unit audits. Pali manual says 24 audits sit in annexure volumes that were not found (V-09, V-21). Terms unread (V-17) |
| **ASI 2023-24 factory microdata** | **Public file `ASI24m.TXT` (610 MB) downloaded** and parsed: 68,641 factories, 600,530 input-item rows. Quantity and value exist only for **electricity (kWh), coal (tonnes) and gas (kg)**; diesel, furnace oil and other fuels carry no quantity (V-19, V-30). Portal terms unread, so only aggregates leave this machine (V-18) |
| ASI 2022-23 and 2021-22 | Need the owner's free login (V-35) |

## 4. First real-data run: ASI 2023-24 (pre-specified, run once)

Small open factories (at most 50 persons): 24,517; 24,154 have at least one usable item; **2,442 have two or
more**; 36 states are the bootstrap clusters. The reference quantity is what the factory *reported*, not a
metered value. All five hypotheses came out supported (Holm-adjusted p = 0.005, the floor for 1,000 draws)
in the main run and in both declared sensitivity runs. Full table and caveats:
[RESULTS_ASI_2023-24.md](RESULTS_ASI_2023-24.md). The points to take away:

1. **Spend divided by a typical state price estimates a fuel quantity well for electricity (median error
   6%), moderately for coal (17%) and LPG (19%); a sector-average guess scaled by headcount is poor
   (median 75%).** The ordering is robust to the settings tried. Pooled figures are 90% electricity.
2. **The placeholder uncertainty ranges are wrong, in different directions per fuel.** Default 90th
   percentile error is 599% against a placeholder of 50%; the nominal 90% interval covered the truth 78% of
   the time; coal and LPG Estimated are about 60% against 25%. Calibration must be per fuel.
3. **The trust index carries information beyond a naive predictor where it can be tested.** Pooled
   rho = -0.97 is largely structural (most factories have one item); among the 2,422 factories with two or
   more items rho = -0.79 (exploratory) against 0.68 for "share of emissions that is Default".
4. **The top hotspot is usually stable** (96% under `bills_only`), much less so when its lead is under 10
   points (57%).
5. **H5 (fix the biggest hotspot first) rests on 67 factories** and its interval nearly touches zero. Treat
   as weak.

## 5. What it does not show

The profiles are simulated assumptions about what a unit records, applied by us, not by real owners; the
reference is reported, not metered; ASI covers registered factories, not informal units; one year; liquid
fuels are absent and they matter most for the small units in CSTEP's data. "Supported" means the
pre-specified falsification condition was rejected, not that the claim is established.

## 6. What is still open

- **Owner decisions:** teacher's view on ASI as a stand-in for informal units; ASI portal terms; sector
  and sample choice (see [DATA_TO_COLLECT.md](DATA_TO_COLLECT.md)); GWP set AR5 vs AR6 (V-05); reading of the
  placeholder range as a 90% interval (V-25).
- **Missing factors:** pet coke, firewood and other biomass, biodiesel, bio-CNG, and densities beyond diesel
  (V-23, V-24). Pet coke matters for the recommended sector.
- **Calibration:** replace class-level ranges with per-fuel ranges and test them on a held-out year.
- **Not run:** any test with real owners; any test on liquid fuels.
