# First results on real data: ASI 2023-24 (DRAFT, read the caveats first)

Run on 2026-10-25 with the analysis and settings pre-specified in `docs/RESEARCH_DESIGN.md` (decisions logged
in §10 *before* the run, timestamp 23:41 IST; the run finished after). Result files are in `outputs/` (gitignored):
`study_asi_2023-24.json` (main), `..._sens_natgas.json`, `..._sens_100.json`. Reproduce:

```bash
python -m greeneis.study.run --source asi --path C:/Users/vitta/greeneis-data/asi/ASI24m.TXT --seed 20261025 --boot 1000 --out outputs/study_asi_2023-24.json
```

## What the data are

ASI 2023-24, unit-level, from the public file `ASI24m.TXT` (see DATA_INVENTORY.md). Main run: open factories
with at most 50 persons (24,517); of these 24,107 report purchased electricity, 978 coal and 1,579 gas, each
with a quantity (kWh, tonnes, kg) and a purchase value. **2,442 factories have two or more of these.** 36
states are the bootstrap clusters. "Gas" is read as LPG (sensitivity: natural gas). Petrol, diesel and other
fuels cannot be used (no quantity is ever reported for them).

**The reference quantity is what the factory reported. It is not metered.** The "Estimated" proxy is spend divided
by the typical price of the same item in the same state (leave-one-out); the "Default" proxy is the
sector's median intensity per person times the factory's own persons.

## The five pre-specified hypotheses

All five come out **supported** (Holm-adjusted p = 0.005, the smallest value 1000 bootstrap draws allow) in the
main run and in both pre-declared sensitivity runs (gas as natural gas; up to 100 persons). Below is what that
does and does not mean, hypothesis by hypothesis.

| H | Main-run numbers | What it really says | Caveat that matters |
|---|---|---|---|
| H1 Default errors exceed Estimated errors | median error 75% (Default) vs 6% (Estimated); difference 0.66, CI 0.64-0.68 | A sector-intensity-times-persons guess is far worse than spend divided by a state price | **Pooled figures are 90% electricity.** Per fuel the Estimated error is much larger for coal (median 17%, 90th percentile 63%) and LPG (19%, 58%) than for electricity (6%, 18%). Electricity does well because tariffs are nearly uniform within a state. The Default proxy is crude by design (persons as scale); a better Default would shrink H1's gap, so H1 is about *these* two proxies |
| H2 Placeholder ranges are miscalibrated | Default 90th percentile error 599% against a placeholder of 50%; pooled coverage of the "90%" interval 78% (band 80-95%) | **The ±50% for Default is far too small** for this proxy, and the heavy tail (30% of Default values are more than double the truth) is not captured by any symmetric range | Estimated pooled 90th percentile (22%) sits inside the placeholder ±25%, but only because of electricity: coal and LPG (about 60%) are well outside it. Calibration should be **per fuel**, not per class |
| H3 Trust index tracks total error | pooled ρ = -0.97; within `random_mix` -0.92 | The index orders factories by error very well | **Mostly structural**: 22,000 of the 24,000 factories have one item, so their error is fully determined by the class assigned. Exploratory check on the **2,422 factories with two or more items** (not pre-specified): ρ(T, error) = **-0.79** within `random_mix`, against 0.68 for the naive "share of emissions that is Default". So T carries some information beyond the naive predictor, but far less than -0.97 suggests |
| H4 Top hotspot is robust | top hotspot kept in 96.4% (CI 95.4-97.3%) under `bills_only`; 57% when the lead over the second is under 10 points, 98% otherwise | The largest activity is usually still the largest | Only among 2,411 factories with electricity plus coal or gas, and a factory has **at most three** activities. In `bills_only` electricity is exact and the fuels are priced well; under `minimal` (all Default) the top hotspot is kept in 83% |
| H5 Improving the largest hotspot's data first helps most | error reduction 0.158 (largest first) vs 0.096 (lowest trust first) vs 0.085 (random); margin 0.062, CI 0.010-0.088 | Fixing the biggest item's data first beats the alternatives | **Only 67 factories in 16 clusters** (98 in the 100-person run). It needs two non-measured items, which `bills_only` rarely gives (electricity is already measured). The interval nearly touches zero. Treat as weak |

## Exploratory (not pre-specified; do not present as confirmatory)

Among the 2,442 factories with two or more items, under each profile (median |total error| / interval covers
the truth / top hotspot kept): `bills_only` 3.4% / 77% / 96%; `invoices_main` 0% / 100% / 100%; `random_mix`
6.7% / 69% / 92%; `minimal` 69% / 29% / 83%. The nominal "90%" interval covered the truth only 77% of the time
under `bills_only` and 69% under `random_mix`: **the placeholder ranges are too narrow where it matters.**

## What this supports, in plain words

1. Estimating a fuel quantity from spend and a typical local price works well for electricity, moderately for
   coal and LPG, and a sector-average guess scaled by headcount works badly. That ordering holds up and is
   not an artefact of the settings tried.
2. The placeholder uncertainty ranges are wrong, and wrong in different directions for different fuels. The
   most useful result for the system is a **per-fuel calibration** table (see below).
3. The Measured / Estimated / Default label carries information about error beyond a naive predictor, in
   the factories where it can be tested (two or more items), with a correlation of about -0.8.
4. The top hotspot is usually stable, less so when the lead is thin.

## What it does not show

- It does not show the trust score works for **real owners**: the profiles are simulated assumptions about what a
  unit records, and the proxies are applied by us, not by owners.
- The reference is reported, not metered; reporting errors (rounding, a wrong unit) are in the "truth".
- ASI covers registered factories (smallest about 10 workers), not informal units, and one year. Whether the
  error sizes carry over to informal units is untested.
- Liquid fuels (diesel, furnace oil) are absent, and they matter most for the small units in CSTEP's data.
- H5 rests on 67 factories; H3's headline is largely structural. "Supported" means the pre-specified
  falsification condition was rejected, not that the claim is established.
- Single year: the leave-one-out proxies share one year's prices. Earlier rounds need the owner's login
  (2022-23, 2021-22) and would allow a true held-out-year test.

## Suggested next steps (each would be a logged change, tested on held-out data)

1. **Per-fuel calibration.** Replace the class-level ranges by fuel-and-class ranges from these errors
   (electricity Estimated ≈ ±18% at the 90th percentile; coal ≈ ±63%; LPG ≈ ±58%; Default needs an
   asymmetric, much wider range or a better proxy). Validate on 2022-23 or 2021-22, which needs the free login.
2. **A better Default proxy** (scale by output or fixed capital instead of persons) and retest H1 and H2.
3. **Report coverage by fuel and an asymmetric interval** in the dashboard, because errors are skewed.
4. Add specific fuels that a minority of factories list among their input items (coal 1101xxx, LPG 3341004,
   diesel 3335xxx, furnace oil 3338001; roughly 1,000 rows) to recover some liquid fuels.
5. Read the portal's terms of use before using any factory-level number in a paper.
