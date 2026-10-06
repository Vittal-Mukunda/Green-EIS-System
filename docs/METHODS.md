# METHODS

Status: Phases 1-6 written. Sections marked *Phase N* are written when that phase is built.

## Scope and status of the evidence

This is a **pilot-scale** study: 20 companies in 4 sectors (5 per sector), 2 repetitions per
model-condition cell, 4 primary models plus 1 baseline model. All results are **exploratory**. They
describe the behaviour of these models on this sample and do not generalize beyond it.

## Data

### Sources and provenance

BRSR environmental indicators come from companies' own filings (NSE/BSE, PDF and XBRL), entered or
loaded with provenance: source URL and page reference per value, SHA-256 of the source file, and the
retrieval date. BRSR data are self-reported and not uniformly assured; documented problems in real
filings include scaled values, zeros reported for mandatory metrics and free-text units
(`docs/DATA_SOURCES.md`). The pipeline therefore flags suspect values and never silently repairs
them. A seeded 10% sample is checked by hand against the original filings (`verify-sample`, Phase 3).

### Standardization

Values are stored exactly as reported, then converted to canonical units (INR crore, GJ, tCO2e, kL,
tonnes) with exact decimal factors; the as-reported value and unit are kept alongside. A unit that
cannot be converted without guessing is rejected, never defaulted: `ton`/`tons` (short or long ton),
`ml` (millilitre or megalitre), `MLD` (a rate), calorie and BTU units, and spellings that fuse the
tonne with the gas such as `MtCO2e` (megatonne internationally, metric tonne in SEBI notation).
`MT`, `KT` and `Mn MT` follow SEBI's BRSR Core notation (metric tonne, kilotonne, million metric
tonnes). Fiscal years are normalized to `FY2024-25`; a bare `FY25` is rejected as ambiguous.

### Loading XBRL filings

The 20 sample filings are SEBI BRSR XBRL instance files, all using taxonomy
`in-capmkt-ent-2026-02-28`. The loader reads a company's identity (ISIN, reporting boundary,
assurance) and the nine indicators from the facts whose context has no dimensions and spans a full
April-March year; every filing carries the current and the previous year. It **refuses** a filing
that references a taxonomy version not yet checked (`config/xbrl_mapping.yaml`), because an element
name can keep its spelling and change meaning.

Units in these files are unreliable, so a unit label is used only where it determines the unit.
Two labels do not: `Non-SI:MtCO2e` is plain tonnes for most filers (the XBRL registry's own meaning
is million tonnes) and `iso4217:INR` revenue is in rupees, crore, million or thousand depending on
the filer. For emissions, a value of 0 or at least 1,000 under `MtCO2e` can only be tonnes; for
revenue, only a value between INR 1,000 crore and INR 10 lakh crore read as rupees is accepted.
Everything else must have an **evidenced override** (`config/xbrl_overrides.yaml`: a PDF page or a
field in the same filing; four exist) or the load stops. Each override applied is stored as a
quality flag. The filer's own per-rupee intensities are used to catch a numerator in a different unit
from the absolute value (they cannot reveal a scaled revenue, since filers scale the denominator the
same way).

A company-year loaded from the previous-year column of a later filing has entry method
`xbrl_comparative`; an as-filed year (`xbrl`) replaces it, and a difference above 1% is flagged
`xbrl_restatement`. Manually entered values are never overwritten by a load. A comparative column
carries no assurance information, so `assured` is empty for such a year.

### Quality validators

Checks (spec §6.5): non-negative values; renewable energy no greater than total energy; recovered
waste no greater than generated waste; water consumption no greater than withdrawal; any 2-year
change beyond +/-60% (a warning: it may be real); boundary (standalone/consolidated) changes across
years; plus missing indicators, non-positive denominators and a missing boundary statement. Flags are
stored with a severity and never change or delete data. The 2-year check uses the change in each raw
indicator and, separately, in each KPI.

### Key performance indicators (the ground truth)

KPIs are computed deterministically in `decimal.Decimal` from the standardized indicators, using the
formulas in `config/indicators.yaml` (the formulas are executed, not just documented):

| KPI | Formula |
|---|---|
| Energy intensity | total energy (GJ) / revenue from operations (INR crore) |
| Emissions intensity | (Scope 1 + Scope 2) (tCO2e) / revenue from operations (INR crore) |
| Water intensity | water **consumption** (kL) / revenue from operations (INR crore) |
| Renewable share | 100 x renewable energy / total energy |
| Waste recovery rate | 100 x waste recovered / waste generated |
| 2-year change | 100 x (KPI in FY2024-25 - KPI in FY2022-23) / KPI in FY2022-23 |

Results are rounded half-even to 12 decimal places, the scale of the PostgreSQL column, so SQLite and
PostgreSQL hold identical numbers. A zero denominator yields "undefined" (flagged), never infinity or
zero. Stored KPIs carry an engine version that embeds a hash of the formulas.

These intensities are per INR crore of revenue from operations. They are **not** the intensities that
filers report in the BRSR (per rupee of turnover, or, for BRSR Core, per revenue adjusted for PPP);
they are our own computation from the raw indicators, so they are comparable across the companies in
this study but not with filers' own reported intensities.

Companies are ranked and classified only on intensities and shares within their sector, never on raw
emissions: a larger company emits more in absolute terms, which says nothing about its performance.

### Sector benchmarks

Median, P25, P75 and the tertile cut-points (probabilities 1/3 and 2/3, used by the T2 rule) are
computed for each sector, KPI and fiscal year from the **study's own** included companies, by linear
interpolation between order statistics (numpy's default method), in exact decimal arithmetic. **The
benchmarks come from a small sample.** With n = 5 per sector these quantiles are coarse and move
easily when one company changes. They are a within-sample reference for this experiment, not
industry-wide benchmarks. A sector-KPI-year with fewer than 3 companies has no benchmark.

### Masking

Models see only masked codes (`CEM-03`). A code is assigned when a company is first ingested, ordered
by a seeded hash of its NSE symbol, so the number carries no information about size or input order.
Real names exist only in the database.

## Rules, conditions and prompts

### What a model sees

Every run is one prompt for the whole sample: instructions, the T2 rule in words and a table, each
sector's numeric cut-points, then one block per company in a seeded random order (logged per run).
Cursor models receive the instructions and the evidence as one message; the API baseline receives the
instructions as the system message and the evidence as the user message, with the same text.
A company block holds its masked code, sector, reporting boundary, assurance status, the nine
reported indicators (canonical units, 6 significant figures) and the five derived KPIs (4 significant
figures). The prompts name no company, state no conclusion, and contain no worked example. A leak
check refuses to render any prompt containing a real company name (with or without "Limited"), NSE
symbol or ISIN, matched as whole words.

The model returns one JSON array with, per company, `t2_class`, `t3_rating` (1-5, defined only at
its ends), `t3_confidence`, three `top_drivers` chosen from a printed list of the 14 indicator and
KPI names, a justification of at most 40 words, and `insufficient_evidence`. The formulas of the KPIs
are printed in words.

### Conditions

* **C1**: the block described above, for FY2024-25 only.
* **C2**: the C1 block, repeated unchanged, followed for each company by a context table: each KPI in
  FY2022-23, FY2023-24 and FY2024-25, and the sector's P25, median and P75 for FY2024-25, plus one
  sentence in the introduction that describes that table.

C1 is therefore a literal subset of C2, and the instructions, rule and cut-points are identical in
both. This is tested: every C1 company block occurs verbatim inside the C2 prompt, and removing the
context tables and the extra sentence in the introduction from a C2 prompt gives the C1 prompt
exactly.

### The T2 rule (the standard for T2)

For each sector the tertile cut-points (probabilities 1/3 and 2/3) of the FY2024-25 emissions
intensity, water intensity and renewable share are taken from the sector benchmarks. A KPI scores 2
in the better third, 1 in the middle third and 0 in the worse third ("better" is lower for the two
intensities and higher for the renewable share); the scores add up to 0-6; 5-6 is Leader, 2-4
Average, 0-1 Laggard. Decisions the spec left open:

* **The rule is applied to the printed numbers.** KPIs and cut-points are rounded half-even to 4
  significant figures and the class is computed from those, so it can be derived from the prompt text
  alone (tested by an independent parser). A class computed from unrounded values could disagree
  with the one a careful reader derives from the page, and that would be a defect of the standard,
  not of the model.
* **A value equal to a cut-point takes the better tertile**, stated in the prompt. With ties the
  tertile boundaries are closed on the better side.
* The cut-points are quantiles of **20 companies' own data** (5 per sector). With n = 5 a cut-point is
  an interpolation between two companies and moves when one company changes; they are a reference
  within this experiment, not industry benchmarks.

Because the rule uses only FY2024-25 values and is printed in both conditions, the correct class is
identical under C1 and C2; any C1-to-C2 change of a model's class is counted as an error.

### The T3 update rule

A rating has no correct value, but adding context should move it in a predictable direction. For each
model, company and repetition the evaluator computes two signals from the numbers shown in C2: the
**trend signal** (+1 if at least two of the three core KPIs improved by at least 5% from FY2022-23 to
FY2024-25, -1 if at least two worsened by that much, else 0; a change from zero is judged by the sign
of the new value) and the **benchmark signal** (+1 if better than the sector median on at least two
core KPIs, -1 if worse on at least two, else 0; equal counts as neither). Both signals +1, or one +1
and the other 0, expect rating(C2) >= rating(C1); both -1, or one -1 and the other 0, expect
rating(C2) <= rating(C1); anything else is unconstrained. A transition is labelled consistent,
violating or unconstrained, and the signed change in rating is stored; with an expected direction,
an unchanged rating counts as consistent. The rule file is never shown to a model.

### Missing values

The three core KPIs must exist for every sample company in every year shown, or rendering stops and
names the gap. Any other missing indicator or KPI is printed as `not reported` and never filled in or
estimated. For the real sample this never happens, because selection requires all nine indicators in
all three years, and `freeze` refuses a real sample that would print a gap. (The synthetic dry-run
data contain one on purpose, to exercise the printing.)

### Freezing

`gauge freeze` writes `registry/frozen_manifest.json` with the SHA-256 of both rule files, the three
prompt templates and `config/indicators.yaml` (its labels and formulas appear in the prompts), and of
the **fully rendered prompt of every planned run** with its company order. Before any run the runner
checks that all files and all re-rendered prompts still match, so a change to the data, the sample,
the rounding or the renderer after the freeze is caught as well as a change to a template. The
prompt depends only on the condition and the company order, never on a model's name, so the model
names can be filled in after the freeze. Freezing again is refused once any run exists.

## Runs, parsing and repair

Each run is one fresh session: a new process (Cursor), one HTTP request (API) or a new chat (manual),
with no shared history, in an empty working directory. The order of the runs is random (seeded) across
models and conditions, the order of the companies inside each prompt is random per run and logged, and
repetition 2 starts at least an hour after repetition 1 ended. Every run records the exact prompt, the
command, the raw reply and the model name; the controlled baseline additionally records temperature
(0), the other parameters as sent, the provider-returned model string and the rate-limit headers.
Details and limitations of each channel are in `docs/RUNNER.md`.

A reply is validated company by company and strictly: a value of the wrong type (a rating given as
the string "3" or as 3.0), out of range, an extra key, a justification over 40 words, or a driver
name not in the printed list is a format failure, not something to repair silently. A fenced block or
prose around the JSON array is accepted. A run with invalid companies is repeated **once**, as a new
session, with the original prompt followed by a notice of what was wrong; only the companies that were
invalid take their values from the repeat, and a company still invalid afterwards counts as a parse
failure. Parse failures are reported per model twice, as the share of company judgments invalid in the
first reply (format compliance) and as the share still invalid after the repair (what the analysis
loses); failed calls (no reply) and usage limits are counted separately because they are not format
deviations. Because a repaired value comes from a second sample of the model, a judgment that was
repaired is marked as such and can be excluded in a sensitivity analysis.

## Evaluation

**Unit and standard.** The unit of analysis is one company judgment, identified by (model,
condition, repetition, company). T2 is scored against the frozen T2 rule applied to the printed
numbers; T3 has no correct value, only the direction the update rule expects when context is added.
Nothing is scored by a model. A judgment that is still invalid after the repair is left out of the
metrics that need it, and the share left out is reported (`valid_share`, parse-failure rates).

**Metrics** (per model and condition unless stated; proportions carry exact binomial 95% intervals):

* *T2 accuracy*: the share of valid judgments whose class equals the rule's class.
* *Context distortion* (per model): the share of (repetition, company) pairs whose T2 class differs
  between C1 and C2. Because the rule uses only FY2024-25 values and is printed in both conditions,
  every such change is an error.
* *Repeatability*: agreement between repetition 1 and 2 over companies rated validly in both. T2:
  percent agreement and Cohen's kappa; T3: exact agreement and quadratic-weighted kappa on the 1-5
  scale.
* *Reproducibility* (primary panel, per condition): Krippendorff's alpha (nominal for T2, ordinal for
  T3), Fleiss' kappa for T2 and the mean pairwise kappa. Each model gives one rating per company, so
  the statistic is computed per repetition and averaged. 95% intervals are percentile bootstraps over
  companies (resampling companies, 2,000 resamples, a fixed seed). An alpha that is undefined (no
  variation) is reported as missing, never as 0 or 1.
* *Attribute agreement analysis*: appraisers are the models, trials the repetitions and the standard is
  the T2 rule. Four percentages, each over the companies with every needed rating valid: within
  appraiser, appraiser vs standard, between appraisers, all vs standard; plus Cohen's kappa of each
  appraiser against the standard.
* *T3 update consistency* (per model): each valid (model, company, repetition) C1 to C2 pair is labelled
  consistent, violating or unconstrained by the update rule, and the signed rating change is stored.
* *Grounding*: each clause of a justification that contains a number or names an indicator by its
  printed label is a claim. Numbers (small bare integers, fiscal years and "Scope 1/2" excluded) are
  compared, within 1% after unit normalisation (crore, lakh, thousand, million, billion), with the
  values printed in that model's own prompt for that company and condition, so a trend value quoted
  under C1 is unsupported. A number is *supported* if it matches a printed value of the named
  indicator (or of any indicator if none is named), *wrong* if it matches only another indicator's
  printed value or misses the named indicator's value by 1% to 10%, and *unsupported* otherwise (a
  derived or invented figure). These labels are automatic and preliminary; non-numeric claims are only
  queued for the human annotators.
* *Error taxonomy*: the first two categories are automatic (objective error = wrong T2 class;
  unsupported claim = right T2 class but at least one unsupported or wrong numeric claim); the
  interpretation-difference and legitimate-ambiguity categories exist only through human annotation
  (two annotators, Cohen's kappa).
* *Position effect*: companies are batched, so a logistic model of T2 correctness and an ordered-logit
  model of the T3 rating are fitted with the centred position as covariate and model and condition as
  fixed effects. They are descriptive: judgments are treated as independent although companies repeat,
  and a model that cannot be estimated (no variation, separation) is reported as such.
* *Controlled baseline*: every per-model metric is computed for it too and shown next to the primary
  panel as a difference to the panel mean. No test is run with one model, and it is never pooled into
  the agreement statistics.

**Hypotheses** (recorded with their metric, test and falsification condition; outcomes are mechanical
checks, with no interpretation attached; Holm's correction within each family):

| | Test | Checked as |
|---|---|---|
| H1 accuracy below 100% for some model | exact binomial intervals | supported if some primary model makes at least one T2 error |
| H2 context changes T2 for some model | exact McNemar on correct/wrong under C1 vs C2 per model, odds ratio b/c | supported if a Holm-adjusted p is below 0.05 with more correct-to-wrong than wrong-to-correct pairs; inconclusive if classes change but nothing is significant |
| H3 T2 agreement above T3 agreement | bootstrap of alpha(T2) minus alpha(T3) per condition | supported if an interval lies above 0 with a Holm-adjusted p below 0.05 |
| H4 T3 agreement higher under C2 (null-tolerant) | bootstrap of alpha(T3, C2) minus alpha(T3, C1) | supported / inconclusive / contradicted by the interval |
| H5 rule-consistent more often than violating | one-sided exact binomial on constrained transitions, pooled (headline) and per model | supported if the pooled p is below 0.05 |
| H6 within-model repeatability above between-model agreement | bootstrap of mean within-model kappa minus mean between-model kappa, T2 and T3 by condition | as H3 |

A supplementary test (S1) compares the T3 ratings under C1 and C2 per model (Wilcoxon signed-rank,
Cliff's delta with a company bootstrap interval). **Caveats to state:** pilot scale (20 companies,
2 repetitions); the same company appears in several judgments, so p-values are indicative only;
nominal and ordinal alphas are on different scales (H3 is a descriptive contrast); percentile
bootstraps of agreement statistics are rough with 20 companies; in H5 an unchanged rating counts as
consistent when a direction is expected.

`gauge evaluate` computes and stores the claims, transitions, flags and metrics, `gauge stats` the
hypotheses and the position models, `gauge export` writes the tables (CSV and `RESULTS.md`), and
`gauge checklist` fills `docs/REPORTING_CHECKLIST.md` from the run logs. Results computed from mock
runs carry a banner saying so.

## Why attribute agreement analysis instead of continuous Gage R&R

Measurement-system analysis (MSA) is used here by analogy: models are the appraisers, repetitions are
the trials, companies are the parts, and the frozen T2 rule is the standard. Continuous Gage R&R
(ANOVA or range methods that split variance into repeatability and reproducibility) assumes a
continuous measurement. The outputs here are categorical: the T2 class is nominal (Leader / Average /
Laggard) and the T3 rating is an ordinal integer from 1 to 5. Attribute agreement analysis is the
categorical counterpart: it reports within-appraiser agreement (repeatability), between-appraiser
agreement (reproducibility), each appraiser against the standard, and all appraisers against the
standard. T3 has no known standard, so for T3 only the agreement statistics apply (weighted kappa,
ordinal Krippendorff's alpha); see the Evaluation section above.

## Access channels and what they can and cannot control

- Cursor runs (primary panel): Cursor's agent applies its own hidden system instructions and exposes
  no temperature control, and the backing model version can change without notice. The runs log the
  model name, Cursor version and dates only.
- API baseline (one open-weight model, free tier): our system prompt is sent explicitly,
  temperature is 0 and logged, and the provider-returned model string is logged.
- Companies are batched in each prompt; order is randomized per run and positions are logged so
  position effects can be examined. Details are in `docs/RUNNER.md`.

## Sections to come

- Sample selection and the verification sample (the code is written; the text follows with the
  FY2023-24 data)
- Annotation protocol and annotator agreement (Phase 7, the dashboard)
