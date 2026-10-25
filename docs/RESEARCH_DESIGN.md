# Research design (DRAFT for owner review, 2026-10-25)

Status: **draft, not approved.** Nothing here is frozen. Numbers marked *placeholder* are design choices,
not findings. Sources are cited by the labels of the reference document
([ref](reference/GreenEIS_Research_and_Design_Reference.docx), `[S#]` = its Source Register).

## 1. Problem and gap

Emission estimates for India's informal manufacturing sector are built top-down (CSTEP 2018 from fuel
supply; CEEW 2018 from survey-based labour inputs) and disagree (110 vs 105 MtCO2e for 2015-16; brick-kiln
coal 26 Mt vs 35-69 Mt) [S1, S2]. Both name the same missing element: validated, firm-level fuel data;
CSTEP asks for "a transparent monitoring system to record fuel consumption by various industries in the
informal sector". A unit that does record its own data will mix metered, estimated and defaulted values.
Existing SME tools either ignore this or rate it without testing the rating against realised error.

**The gap this project addresses:** whether a simple data-class label (measured / estimated / default) on
each input tells a unit's manager how far to believe its footprint and its hotspot ranking, and where
improving the data is worth the effort. The label and its numbers (ref §6.5) are currently *placeholders*
(scores 1.0 / 0.6 / 0.3; ranges ±5% / ±25% / ±50%); no one has shown they are right.

## 2. Research question

> **RQ.** For small Indian manufacturing units, how well do data-class labels (measured / estimated /
> default) predict the error of a unit's calculated emissions and the stability of its hotspot ranking, and
> does using them to decide which data to improve first outperform ignoring them?

Sub-questions: (a) how large are the realised errors of "estimated" and "default" inputs against measured
values; (b) are the placeholder ranges calibrated; (c) does the trust index track realised error; (d) when
is the top hotspot robust; (e) which improvement rule reduces error fastest.

## 3. Design in one paragraph

Take real units for which an energy audit gives **measured** annual fuel, electricity and cost data. The
audit values are the reference ("measured baseline"). For each unit, re-derive each input the way a small
unit without that measurement realistically would: **Estimated** = a proxy computed from other quantities the
audit also reports (spend ÷ typical price; rated power × hours × load factor; stock opening/closing);
**Default** = cluster-typical value scaled by unit size or production (leave-the-unit-out). The gap between
the re-derived value and the measured value is the **realised error**. Run the GreenEIS engine on measured
and on degraded inputs, under several *data-quality profiles* (e.g. "bills only", "minimal"), and compare
totals, trust index, and hotspot rankings. This is a **simulation of data-quality conditions on real
measurements**, not an observation of how owners actually behave.

## 4. Hypotheses (each with its measure and what would falsify it)

Unit of analysis is the **unit** (cases from one unit are not independent): use cluster bootstrap by unit,
report confidence intervals, Holm correction over H1-H5. Thresholds are placeholders to confirm.

| # | Hypothesis | Measure and test | Falsified if |
|---|---|---|---|
| H1 | Default inputs have larger realised error than Estimated inputs | per unit×activity \|ε\| = \|x̃ − x\|/x; paired Wilcoxon, D vs E | median difference ≤ 0 or its 95% CI includes 0 |
| H2 | The placeholder ranges are miscalibrated | q90 of \|ε\| per class vs placeholder u; coverage of the nominal-90% total interval T̃(1±U) over the true total | q90 within [u/1.5, 1.5u] for both classes **and** coverage within [80%, 95%] |
| H3 | The trust index tracks realised total error | Spearman ρ between index T and \|ε_total\|, expected negative, **pooled across profiles and within the random_mix profile** (revised 2026-10-25, see §10) | either correlation is not negative in the bootstrap replicate |
| H4 | The top hotspot is usually robust, but less so when the lead is thin or its data are weak | P(top-1 degraded = top-1 measured) with CI; logistic model on lead gap (share #1 − #2) and class of #1 | lower CI bound on P under the "bills only" profile < 80%, or no association with lead gap |
| H5 | Upgrading the **largest hotspot's** input first cuts total error more than upgrading the lowest-trust item or a random item | paired reduction in \|ε_total\| after one upgrade, per rule | largest-first is not better than both alternatives (CI of paired difference includes 0) |

H1-H3 test the trust score itself; H4-H5 test the hotspot and prioritisation logic that the reference
document asserts without evidence (ref §6.5, §6.6, §8.2).
A secondary, descriptive comparison: does T beat a naive predictor "share of emissions from Default
inputs"? Reported, not tested.

## 5. Procedure and data

1. **Data gate (Phase 1a, before the study is committed to):** inventory unit-level audits we can
   legitimately obtain (SAMEEKSHA cluster manuals and annexures; archived or re-hosted BEE audits; any unit
   the owner can reach). **Go** if ≥ 20 units from ≥ 2 clusters have usable measured fuel and electricity
   quantities plus at least one proxy variable (cost, hours, production, rated load). *Placeholder
   threshold.* Each source's terms of use are recorded.
2. Engine reproduces published arithmetic first (Phase 1c): ref §7 worked example and CSTEP table rows.
3. Build proxies and defaults from documented rules fixed **before** looking at the errors; log them.
4. Run the simulation; compute outcomes; apply the pre-specified analysis; report all five hypotheses,
   including the ones that fail.

**Fallback if the gate fails (Tier B).** Generate units from published cluster typical-unit tables
(micro/small/medium), with stated error models for Estimated and Default. H1-H3 then become circular
(the answer is the assumption) and are **dropped**; only H4-H5 are reported, as "conditional on the assumed
error model". The contribution then shrinks to a design plus a sensitivity study, and the paper must say
so. The owner decides whether to proceed on Tier B.

## 6. Validation of the engine (not hypotheses)

- Reproduces ref §7 (hand calculation, test_engine.py and test_analysis_modules.py): 38.97 tCO2e (13.086 +
  18.91155 + 5.47239 + 1.49625), trust index 0.7228, uncertainty ±12.886%, scenarios 0.82 / 1.89 / 2.62 /
  5.33 tCO2e. Done.
- Recomputes all 56 cells of CSTEP Table 8 from Table 7 and the report's own factors (validation.py,
  test_validation.py). A cell matches when within 1% or one unit of the last printed decimal. **43 match;
  13 are flagged, not corrected:** furnace oil 2012-13 to 2015-16 (published about 9-16% of the recomputed
  value, ratio 0.09-0.16), **naphtha in all eight years** (ratio 0.87-2.64, not mentioned in the reference
  document, which tested only furnace oil and diesel) and LPG 2015-16 (published 0.22, recomputed 0.18).
  Diesel (HSDO), LDO, kerosene and LSHS reproduce in every year. Causes unverified (V-22); the authors have not
  been contacted.
- Unit labelling: factors are stored in kg/TJ with units explicit (CSTEP prints "kt/TJ").

## 7. Threats to validity (state in the paper)

- Audited units joined an efficiency programme; they are not representative of the informal sector.
- "Measured" audit values are the reference but carry their own error and some auditor estimates.
- Our proxies and defaults simulate owners; real owners may err differently (more, or less).
- Small N and few clusters: pilot-scale, results do not generalise beyond this sample.
- Annual audit data cannot test the system's monthly entry; the monthly workflow is a design feature,
  not a tested one (optional: a 3-5 person usability check, reported separately).
- Placeholder scores and thresholds are tuned by nobody on this data; changing them after seeing results
  is not allowed (sensitivity analysis only).

## 8. Out of scope

Process emissions, Scope 3, LCA, real-time sensors, certification, bill/invoice OCR (ref §5.4, §8.3).

## 9. Open decisions for the owner

1. Is "gap paper" CSTEP (2018), as assumed, or another paper?
2. Accept Tier B as a fallback, or stop and re-plan if the data gate fails?
3. Are H1-H5 the right five, or is that too many for the time available? (Cheapest cut: drop H5.)
4. Interpretation of the placeholder ±u as a nominal 90% interval (needed for H2). Alternative: 1 SD.
5. Greenhouse-warming potentials: AR5 (28 / 265) to match CSTEP, or AR6? Draft uses AR5, parameterised.

## 10. Change log (before any real data)

- **2026-10-25, H3 made two-part.** The first draft tested only the pooled correlation between the trust
  index and total error. On synthetic data that correlation was -0.85, but most of it comes from profiles
  differing in class mix *by construction* (the "minimal" profile always has T = 0.3), so it would look
  strong whatever the index is worth. H3 now also requires a negative correlation **within** `random_mix`,
  where the class mix varies unit by unit. Decided before any real data exist; the thresholds were not tuned
  on results.
- **2026-10-25, validation finding broadened.** The reference document reported only the furnace-oil
  anomaly; the full recomputation also flags naphtha (all years) and LPG 2015-16 (§6).
- **2026-10-25, implementation notes that matter for interpretation.** Bootstrap clusters are state-year
  groups (prices are shared within them). With fewer than 10 clusters the analysis refuses to give a verdict.
  The nominal interval is read as a 90% interval for H2 (decision 4 in §9 is still open).
