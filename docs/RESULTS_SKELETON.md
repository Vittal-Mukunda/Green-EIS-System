# Results skeleton

Maps each table and figure of `notebooks/analysis.ipynb` (and the CSV files of `gauge export`) to the
hypothesis or question it answers. It states what each item **is** and what numbers to report; it
makes no claim about what they mean. The sentences marked **[owner]** are yours to write after the
real runs. Everything is pilot-scale and exploratory (20 companies, 2 repetitions, 4 primary models and
one controlled baseline).

Regenerate everything with `gauge evaluate`, `gauge stats`, `gauge export`, `gauge checklist`, then run
the notebook (`GAUGE_CONFIG=config/study.yaml`). Files appear in `data/processed/results/` (tables and
`RESULTS.md`) and `data/processed/results/notebook/` (notebook tables as CSV, figures as HTML).

## 1. Data and method

| Item | Source file | What it is | Report |
|---|---|---|---|
| Table 1 | `sample.csv` | companies per sector, analysis-year boundary, assurance and entry method | the sample size per sector; the mix of standalone and consolidated boundaries; how many reports are as-filed vs a comparative column |
| Table 2 | `selection_log.csv` | every excluded company and the reason | the reasons |
| Table 3 | `data_quality.csv` | data-quality flags by rule | counts, and that flags never change data |
| Table 4 | `verification.csv` | the 10% verification sample against the filings | the error rate among values checked |

**[owner]** Data section: sources, the XBRL unit handling, the verification result (`docs/METHODS.md`,
`docs/DATA_SOURCES.md`).

## 2. Model behaviour (descriptive)

| Item | Source file | Answers | Report |
|---|---|---|---|
| Table 5, Figure 1 | `scorecard.csv` | T2 accuracy against the frozen rule, valid share, repeatability, per model and condition | accuracy with its interval; repeatability agreement and kappa |
| Table 6, Figures 2-3 | `context_effects.csv` | context distortion; T3 rating shift; consistent / violating / unconstrained transitions | rates with intervals |
| Table 11 | `baseline_vs_panel.csv` | the controlled baseline next to the panel (differences, no tests) | the difference to the panel mean per metric |
| Table 14 | `parse_failure_rates.csv` | format compliance per model before and after the one repair | first-reply and final rates; failed calls |

## 3. Agreement and measurement-system analysis

| Item | Source file | Answers | Report |
|---|---|---|---|
| Table 7, Figures 4-5 | `agreement_between_models.csv` | reproducibility between models: Krippendorff's alpha (T2 nominal, T3 ordinal), Fleiss' kappa, pairwise kappa, with company-bootstrap intervals | the estimates and intervals per condition |
| Table 8 | `attribute_agreement.csv` | within appraiser, appraiser vs standard, between appraisers, all vs standard (T2) | the four percentages with exact intervals, and kappa against the standard |

## 4. Hypotheses (mechanical outcomes only)

Table 9 (`hypotheses.csv`) gives each hypothesis with its metric, its test, its falsification condition
and the outcome of that check; Table 10 (`hypothesis_tests.csv`) gives the numbers behind it.

| Hypothesis | Statement | Metric | Test | Table 10 rows |
|---|---|---|---|---|
| H1 | T2 accuracy is below 100% for at least one model | `t2_accuracy` | exact binomial intervals | H1: one row per primary model and condition |
| H2 | T2 class changes between C1 and C2 for at least one model | `t2_context_distortion` | exact McNemar per model, Holm across models, odds ratio | H2: one row per primary model |
| H3 | agreement between models on T2 is higher than on T3 | alpha(T2) minus alpha(T3) | company bootstrap per condition, Holm across conditions | H3: one row per condition |
| H4 | T3 agreement is higher under C2 than under C1 (null-tolerant) | alpha(T3, C2) minus alpha(T3, C1) | company bootstrap | H4: one row |
| H5 | C1 to C2 rating changes are rule-consistent more often than violating | consistent vs violating transitions | one-sided exact binomial, pooled and per model | H5: pooled row, then per model |
| H6 | within-model repeatability is higher than between-model agreement | within-model kappa minus between-model kappa | company bootstrap, Holm across the four tests | H6: T2 and T3 by condition |
| S1 (supplementary) | the T3 rating differs between C1 and C2 | Cliff's delta, Wilcoxon signed-rank | per model, Holm across models | S1: one row per primary model |

**[owner]** For each hypothesis: state the pre-defined check, report the estimate, interval and
adjusted p, and say whether its falsification condition was met. Say plainly that the study is
exploratory and that p-values are indicative because judgments are correlated.

## 5. Position, grounding, annotation

| Item | Source file | Answers | Report |
|---|---|---|---|
| Table 12, Figure 6 | `position_effect.csv` | does a company's position in the prompt relate to T2 correctness or the T3 rating | odds ratios per position and accuracy by third; whether a model could be estimated |
| Table 13 | `grounding.csv` | share of numeric claims supported / unsupported / wrong; the automatic part of the error taxonomy | rates with intervals; number of claims awaiting annotation |
| (notebook, last cells) | annotation tables | annotator agreement | Cohen's kappa for claim support and for the taxonomy |

**[owner]** The grounding labels are automatic and preliminary (`docs/VERIFY.md` V-36): report them
after the annotators have confirmed or corrected them, and report how many were changed.

## 6. Reporting items

`docs/REPORTING_CHECKLIST.md` maps each GUIDE-LLM / MI-CLEAR-LLM minimum item to this study from the
run logs. Table 15 (`run_counts.csv`) is the number of runs by model, condition, repetition and status.

## Limitations to state

* Cursor's agent adds its own hidden system instructions.
* The temperature cannot be controlled for the Cursor runs.
* The backing model versions may change without notice. Mitigation: a fully controlled open-model API
  baseline, plus the reporting checklist.
* Companies are batched in each prompt (order randomised and logged; position effect reported).
* The study is pilot-scale; results do not generalise beyond this sample.
* The sector benchmarks and the T2 cut-points come from this small sample, and the T2 rule is applied
  to the printed (rounded) numbers.
* BRSR data are self-reported and only partly assured; the mixed reporting boundary (standalone and
  consolidated) is a feature of the sample.

## What not to claim

Write "the model output ..." rather than attributing views or beliefs to a model, and do not claim:

* that a model has a point of view of its own;
* that one model is better because its text sounds better;
* that the reported BRSR figures can be taken at face value (they are self-reported and partly assured);
* that an SDG mapping is evidence of achievement; the caption to use is "mapping indicates relevance, not achievement";
* that lower raw emissions make a company greener (the study ranks intensities within sector);
* that a model's own justification is the reason for its decision;
* that pilot-scale results generalise beyond this sample.
