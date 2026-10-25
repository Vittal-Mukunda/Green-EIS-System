# Phase 1 spec: data gate and calculation core (DRAFT for owner review)

Status (2026-10-25): **1b and 1c are built and tested; 1a is run and the gate is not met** (see
DATA_INVENTORY.md). The owner waived per-phase approval for work that does not depend on real data, so the
trust score, hotspot, cost, what-if, recommendation and report modules, the study harness and the dashboard
were built as well (CLAUDE.md section 4). Differences from the draft below: the fuel library has 9 entries
(CSTEP lists HSDO and LDO with one factor set, so both map to `diesel`); the CSTEP check recomputes all 56
cells and flags 13 (furnace oil, naphtha, one LPG cell), which is more than the draft expected; the coal
CO2 figure in the draft table is 18.78 (exactly 18.77876), total 38.97 (38.966190955).

## Goal

Know whether the study's data exist, and have a tested engine that turns a unit's activity data into
tCO2e with every factor traceable. No trust score, simulation, report or UI yet.

## 1a. Data gate

**Do:** inventory the unit-level audit sources we can legitimately use.

- Known so far (probed 2026-10-25): BEE-hosted unit audit PDFs (Pali textile, Indore food, Ludhiana forging)
  now redirect to BEE's homepage from this machine. SAMEEKSHA (sameeeksha.org) still serves PDFs;
  its Pali cluster DPR gives **typical-unit** figures (micro / small / medium) and cluster totals, not
  unit audits. The Pali cluster manual's appendix reportedly lists 24 unit audits in annexure volumes
  (`TODO(verify)`). Wayback Machine copies of the BEE PDFs are unchecked (rate-limited).
- For each candidate source record: cluster, number of units, fields present (fuel quantity, kWh, cost,
  hours, production, rated load), who measured them, licence or terms, how it was obtained.
- Downloads: **I ask before each batch** (filename, source, size) per the project rules.

**Output:** `docs/DATA_INVENTORY.md` with a go / no-go against the gate in RESEARCH_DESIGN §5
(≥ 20 units, ≥ 2 clusters, usable proxy variable). On no-go, present Tier B and stop.

## 1b. Factor library

- Table of fuels: NCV (TJ/kt), EF CO2 / CH4 / N2O (kg/TJ), density, source label, year, status.
  Start from CSTEP Table A.5 (ref Appendix A); electricity from the CEA CO2 Baseline Database.
- Open items, each in `docs/VERIFY.md` and marked `TODO(verify)` in the data: CEA grid factor (0.727 /
  0.757 tCO2/MWh comes from a trade-press report, check the CEA release); natural-gas CO2 factor
  (printed "56.100") and its volumetric NCV; fuel densities (diesel 0.85 kg/L is ref §7's assumption);
  coal grade default; GWP set (AR5 28/265 to match CSTEP).
- No factor enters the library without a value, a unit, a source label and a year.

## 1c. Calculation engine

- A pure Python module, no UI imports, `Decimal` throughout. Inputs: activity quantity and unit per fuel,
  electricity kWh. Steps: unit conversion (stored densities) → energy (TJ) → CO2, CH4, N2O → CO2e → total.
- Explicit rejection of ambiguous units; every result carries the factor ids it used.
- Briquetting = 0 and coking factor as in CSTEP; unknown coal grade uses the sub-bituminous default and
  raises a flag (consumed by the Phase 2 trust score).

## Acceptance tests (hand-calculated literals only)

| Test | Expected |
|---|---|
| Ref §7 grid electricity, 18,000 kWh at 0.727 | 13.09 tCO2e (13.086) |
| Ref §7 coal, 10,000 kg | 18.91 tCO2e (CO2 18.78 + CH4 0.055 + N2O 0.078) |
| Ref §7 diesel 1,700 kg and LPG 500 kg | 5.47 and 1.50 tCO2e; total 38.97 |
| CSTEP HSDO 2008-09, 1,469 kt | 4.7288 Mt recomputed; published 4.70 (within 1%) |
| CSTEP FO 2015-16, 2,564 kt | 8.0029 Mt recomputed; published 0.84 → flagged, not corrected |
| Unit conversion litres → kt via density | exact decimal results, no float drift |
| Missing factor / unit / source | raises, never defaults silently |

Test values above are my hand calculations from the printed tables; each is re-derived independently in
the test file's comments, never by calling the engine.

## Not in Phase 1

Trust score and uncertainty, the simulation, hotspot/cost/what-if modules, report, any page. The kept
frontend is not touched except as needed.

## Deliverables and stop

`docs/DATA_INVENTORY.md`, the factor library, the engine with tests, `docs/VERIFY.md` updated.
Then I summarise (built / test results / open issues) and wait.

## Next (not committed)

Phase 2: trust score, hotspot, cost link and the degradation simulation. Phase 3: analysis of H1-H5.
Phase 4: new interface screens on the kept design system. Phase 5: report and paper skeleton.
