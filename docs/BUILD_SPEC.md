# Build prompt for Claude Code — "LLM Gauge" Green EIS (subscription-only version)

> Verbatim copy of the owner's build prompt, stored so that section references (§4.5 etc.) in
> CLAUDE.md, code comments and docs resolve. Do not edit; if the design must change, the owner
> changes it here deliberately.

You are building a complete, reproducible research system in this repository. Read this whole document before writing any code. The design decisions below are final unless you find a concrete technical reason one cannot work. If you do, stop and tell me; do not silently change the design.

---

## 0. Context (copy the essentials into CLAUDE.md)

**Project:** "Is the LLM a Reliable Gauge? A Green Enterprise Information System for Measurement-System Analysis of Multi-LLM Interpretation of Indian BRSR Sustainability Evidence."

**Owner:** an undergraduate Industrial Engineering & Management student. This is an Enterprise Information Systems course project, intended to become a short paper.

**Tooling and budget (fixed — no paid APIs):**
- **Building:** you (Claude Code), running on my $20 Claude subscription. Work in phases and stop at each gate so the usage limits are not exhausted mid-phase.
- **Running the primary models:** my $20 **Cursor** subscription, through Cursor's command-line agent (`cursor-agent`), driven by a Python runner script. There must also be a **manual fallback**: I paste prompt files into Cursor chat and save the responses.
- **Controlled baseline:** **one open-weight model** called directly through a **free API tier** (OpenRouter `:free` model, default `openai/gpt-oss-120b:free`; fallback Groq free tier). This is the fully reproducible reference point: no hidden system prompt, temperature fixed and logged. It costs $0 and needs one free API key.
- No paid API spending anywhere.

**Why the baseline exists:** reporting guidelines for LLM studies (e.g., GUIDE-LLM, MI-CLEAR-LLM, the empirical-SE LLM guidelines) treat the system prompt, the exact model version and the temperature as minimum reporting items. Cursor applies its own system prompt to every agent run and does not expose the temperature, so the Cursor runs can't meet those items. The API baseline can, and the empirical-SE guidelines also recommend an open model as a baseline.

**What the system does:**
1. Ingests BRSR environmental data.
2. Standardizes it.
3. Computes deterministic KPIs, trends and sector benchmarks. These form the **ground truth**.
4. Renders the same evidence into **2 controlled conditions**.
5. Runs **4 Cursor models × 2 conditions × 2 repetitions = 16 runs**, plus **4 baseline runs** (1 open model via free API × 2 conditions × 2 repetitions), with all study companies batched in each prompt. That is 20 runs in total.
6. Imports the outputs and scores them.
7. Shows the results in a management dashboard.

**Critical principle:** models receive *evidence*, never our conclusions. The T2 rule class and all evaluation results are never shown to any model.

**Self-preference control:** you (Claude) build the prompts, so Claude models are **excluded from the primary panel**. An optional 4-run Claude sensitivity check is described in §4.7.

**First action:** create `CLAUDE.md` summarizing sections 0, 2, 4 and 11.

---

## 1. Stack (fixed)

- Python 3.11+, `uv` (fall back to pip + requirements.txt)
- SQLite via SQLAlchemy 2.x, with a Postgres-compatible schema
- pydantic v2 for data models and the output schema
- pandas, numpy
- scipy, statsmodels, and the `krippendorff` package
- Streamlit + Plotly for the dashboard
- typer for the CLI
- pytest and ruff

---

## 2. Hard rules

1. **The runner never uses the Cursor agent in a project folder.** Every model run executes inside an **empty, isolated sandbox directory** (`runs/sandbox/` — no code, no data, no .cursor rules). The prompt text is passed in directly. This ensures no project files leak into the model's context.
2. **One fresh session per run.** Runs share no conversation history.
3. **Before writing the runner**, read `cursor-agent --help` and Cursor's CLI documentation. Use only flags that actually exist for:
   - non-interactive / print mode
   - model selection
   - output format
   - disabling or limiting tool use and file edits

   Record the CLI version and the exact command in `docs/RUNNER.md`. If a capability doesn't exist (e.g., tools can't be disabled), document it as a limitation; do not fake it.
4. **The model name must be explicit.** Never use "auto". The run fails if a model name in `config/models.yaml` is a placeholder or isn't listed by the CLI's model listing (if the CLI provides one).
5. **Log everything for each run:**
   - run ID, timestamp (UTC), CLI version, model name, condition, repetition, seed
   - the exact command
   - full prompt text and its SHA-256
   - raw stdout and stderr
   - exit code
   - duration

   Save the raw output to `runs/raw/{run_id}.txt` **before** parsing.
6. **Runs are resumable and idempotent.** A run with an existing successful raw file is skipped unless `--force` is given.
7. **Rules and prompt templates are frozen** (SHA-256 manifest) before the first real run. The runner refuses to start if any frozen file has changed.
8. **Never invent data**, BRSR field names, XBRL element names, CLI flags, or model names. Unverified items get `TODO(verify)` and go in `docs/VERIFY.md`.
9. **Company names are masked** in every prompt (e.g., "CEM-03"). The mapping lives only in the DB.
10. **Rank and classify only on intensities and within-sector comparison**, never on raw emissions.
11. **Pause between runs** (configurable delay, default 20 s) to stay within plan rate limits. If the CLI reports a usage-limit error, stop cleanly and resume later.
12. **Baseline API runs** read the key from `.env` (`OPENROUTER_API_KEY`, or `GROQ_API_KEY` for the fallback), which is gitignored.
    - Use **only `:free` model IDs**, and fail if a configured ID doesn't end in `:free` (on OpenRouter).
    - Set `temperature=0` and log the value. Log `top_p`, `max_tokens` and `seed` if supported, plus the provider-returned model string and any response headers about rate limits.
    - Send **our** system prompt explicitly. It is identical to the instructions given to the Cursor models, just placed in the system role.
    - If the batched prompt exceeds the free tier's token limits, split the batch by sector, document it, and apply the same split to all baseline runs.

---

## 3. Repository layout

```
.
├── CLAUDE.md  README.md
├── config/      study.yaml  models.yaml  indicators.yaml
├── data/        raw/ (gitignored)  manual_entry_template.csv  processed/
├── registry/    rules/  prompts/  frozen_manifest.json
├── runs/        sandbox/ (always empty)  prompts/  raw/  manual_inbox/
├── src/gauge/
│   ├── db/ ingest/ standardize/ quality/ kpi/ benchmark/ sdg/
│   ├── rules/ render/ runner/ parse/ evaluate/ msa/ stats/
│   └── cli.py
├── dashboard/app.py
├── notebooks/analysis.ipynb      # imports from src/, reads from DB only
├── tests/
└── docs/  METHODS.md  RUNNER.md  DATA_SOURCES.md  VERIFY.md  schema.sql
```

---

## 4. Study design (implement exactly)

### 4.1 Sample
- **Sectors:** Cement, Iron & Steel, IT Services, FMCG.
- **Companies:** **5 per sector, 20 in total** (`study.yaml` allows raising this to 10 per sector).
- **Selection rule:** within each sector, the largest companies by market capitalization that are required to file BRSR and have complete core indicators for FY2022-23, FY2023-24 and FY2024-25. Log every exclusion with its reason.
- **Analysis year:** FY2024-25. Earlier years are used for trends.

### 4.2 Core indicators (BRSR Principle 6 essential indicators — verify exact fields)
- revenue from operations
- total energy and renewable energy (GJ)
- Scope 1 and Scope 2 (tCO2e)
- water withdrawal and water consumption (kL)
- waste generated and waste recovered (t)
- reporting boundary (standalone / consolidated)
- assurance status

**Derived KPIs** (deterministic engine, using decimal arithmetic, with ≥5 hand-calculated unit tests):
- energy intensity
- emissions intensity (Scope 1+2 per ₹ crore)
- water intensity
- renewable share
- waste recovery rate
- 2-year % change for each of the above

**Sector benchmarks:** median, P25 and P75 of each intensity, computed from our own sample. Note in METHODS.md that the benchmarks come from a small sample.

### 4.3 Conditions (2)

| Code | Content | Format |
|---|---|---|
| **C1 (baseline)** | raw indicators + derived KPIs, FY2024-25 only | Markdown table, one block per company |
| **C2 (context)** | C1 + 3-year trend (FY23/FY24/FY25 intensities) + sector median, P25 and P75 | same format |

The only difference between C1 and C2 is the added trend and benchmark context. Write a test that verifies every C1 value appears identically in C2.

SDG mappings are informational and appear in the dashboard only, with the caption: "mapping indicates relevance, not achievement".

### 4.4 Task (one combined prompt per run)

For **every company** in the batch, the model returns a JSON object with:
- `company_code`
- `t2_class`: Leader / Average / Laggard, applying the rule in §4.5, which is printed in full in the prompt
- `t3_rating`: 1–5, the model's own overall environmental performance assessment
- `t3_confidence`: 1–5
- `top_drivers`: 3 indicator names, ranked
- `justification`: at most 40 words; every claim must name the indicator it uses
- `insufficient_evidence`: boolean

The whole response is a single JSON array. The prompt must state:
- use only the evidence given;
- assess each company independently;
- give no text outside the JSON.

**Company order** in each prompt is randomized with a seed that differs per run. Log each company's position, so position effects can be checked.

### 4.5 T2 rule (`registry/rules/t2_v1.yaml`, frozen)

For each sector, compute tertile cut-points on FY2024-25 data for three metrics:
- emissions intensity (lower is better)
- water intensity (lower is better)
- renewable share (higher is better)

Score each metric: best tertile = 2, middle = 1, worst = 0. Sum the scores:
- 5–6 → Leader
- 2–4 → Average
- 0–1 → Laggard

The rule text and each sector's numeric cut-points appear in the prompt under **both** conditions. Because the rule is fully specified and uses only FY2024-25 values, **the correct class is identical under C1 and C2**. Any change in T2 class from C1 to C2 is therefore an error: added context distorting a rule-based judgment.

### 4.6 T3 update rule (`registry/rules/t3_update_v1.yaml`, frozen)

For the C1→C2 transition (same model, company and repetition index):
- **Trend signal:** +1 if ≥2 of 3 core intensities improved ≥5% from FY23 to FY25; −1 if ≥2 worsened ≥5%; otherwise 0.
- **Benchmark signal:** +1 if the company is better than the sector median on ≥2 of 3 core metrics; −1 if it is worse on ≥2; otherwise 0.
- **Expected direction:**
  - both signals +1 (or one +1 and the other 0) → rating(C2) ≥ rating(C1)
  - both −1 (or one −1 and the other 0) → rating(C2) ≤ rating(C1)
  - conflicting signals, or both 0 → unconstrained
- Label each transition **consistent**, **violating** or **unconstrained**, and store the signed change in rating.

### 4.7 Models and runs (`config/models.yaml`, `study.yaml`)

- **Primary panel: 4 non-Claude models** available in my Cursor plan, from different vendors where possible (e.g., an OpenAI GPT model, a Google Gemini model, an xAI Grok model, and one more). I fill in the exact names shown by Cursor on the day of the run. They must not change mid-study.
- **Runs:** 4 models × 2 conditions × 2 repetitions = **16 runs**.
  - Run order is randomized (seeded) across models and conditions.
  - Repetition 2 starts ≥1 hour after repetition 1.
- **Controlled baseline (required):** 1 open-weight model via free API (§2.12) × 2 conditions × 2 repetitions = **4 runs**.
  - The baseline is reported **alongside** the primary panel, never pooled into the cross-model agreement statistics.
  - Use it for a **channel check**: if the baseline's C1→C2 behaviour (T2 distortion, update consistency, repeatability) resembles the Cursor models', the Cursor wrapper is less likely to explain the findings. If it differs sharply, report that as a caveat.
  - If the same model family is available both in Cursor and as a free API model, prefer it, so that the access channel is the only difference. Document whether this was possible.
- **Optional sensitivity check:** 1 Claude model × 2 conditions × 2 repetitions = 4 runs. These are reported separately and never pooled with the primary panel.
- **Optional extension** (only if time allows): a leave-one-indicator-out check on C2.
  - Make 3 extra variants, each with one indicator group shown as "not reported": emissions, water, renewables.
  - Run them × 4 models × 1 repetition = 12 runs.
  - Compare each model's stated `top_drivers` with which removal actually changed its ratings. This gives a crude faithfulness check.

### 4.8 Runner (`src/gauge/runner/`)

- **`render` command:** writes each run's prompt to `runs/prompts/{run_id}.md` and adds the run to `runs/manifest.csv` (run ID, model, condition, repetition, seed, prompt hash).
- **Automatic mode (`run --mode cli`):** for each pending run, call the Cursor agent from `runs/sandbox/` with the verified flags, capture the output, log it, pause, then continue.
- **Manual mode (`run --mode manual`):** print the instructions:
  1. Open a new Cursor chat in an empty folder.
  2. Select model X.
  3. Paste `runs/prompts/{run_id}.md`.
  4. Save the reply to `runs/manual_inbox/{run_id}.txt`.

  The `import-manual` command then ingests the inbox files with the same logging.
- **API mode (`run --mode api`, baseline only):** an OpenAI-compatible HTTP client (httpx + tenacity) for OpenRouter and Groq.
  - Retry with backoff on HTTP 429.
  - Make the run resumable through the same raw-file cache.
  - Store the full request body (minus the key) and the full response JSON.
- **Parsing:**
  - Extract the JSON array and validate it with pydantic.
  - If it is invalid, re-run that run **once** with a short repair instruction appended (logged as a repair), then record `parse_failure` for any companies still invalid.
  - Report parse-failure rates per model.

---

## 5. Evaluation

**Unit of analysis:** one company judgment, identified by (model, condition, repetition, company). With 20 companies this gives 320 judgments in the primary panel.

### Metrics
- **T2 accuracy:** model class vs. rule class, per model and condition.
- **T2 context distortion:** the % of companies whose T2 class changes from C1 to C2 (same model and repetition). Every such change is an error.
- **Repeatability:** agreement between repetitions 1 and 2, within each model and condition.
  - T2: % agreement and Cohen's κ
  - T3: weighted κ (quadratic)
- **Reproducibility (between models):** per condition, with a 95% bootstrap CI (2,000 resamples over companies).
  - T2: Fleiss' κ / nominal Krippendorff's α
  - T3: ordinal Krippendorff's α
- **MSA — attribute agreement analysis:**
  - appraisers = models, trials = repetitions, standard = T2 rule
  - report within-appraiser agreement, between-appraiser agreement, each appraiser vs. the standard, and all appraisers vs. the standard
  - in METHODS.md, explain why this is used instead of continuous Gage R&R
- **T3 update consistency:** the % of C1→C2 transitions that are consistent, violating or unconstrained, per model.
- **Grounding:**
  - Treat each clause in `justification` that contains a number or names an indicator as a claim.
  - Extract numbers with regex and match them against the input values or KPIs within 1%, after unit normalization. Label each numeric claim supported, unsupported or wrong.
  - Queue non-numeric claims for human annotation in the dashboard.
- **Position effect** (because companies are batched): test whether T2 accuracy or the mean T3 rating varies with the company's position in the prompt (logistic / ordinal model with position as a covariate). Report it descriptively.
- **Four-way error taxonomy:** objective error / unsupported claim / interpretation difference / legitimate ambiguity.
  - The first two are assigned automatically.
  - The last two are assigned only through human annotation (2 annotators; report Cohen's κ).

**No LLM-as-judge anywhere in the scoring.**

### Hypotheses (`stats/hypotheses.py`; each records its metric, test and falsification condition)
- **H1:** T2 accuracy is below 100% for at least one model; the models are imperfect rule appliers. Report exact binomial CIs.
- **H2:** T2 class changes between C1 and C2 for at least one model (context distortion > 0). Use McNemar per model.
- **H3:** Agreement between models on T2 is higher than on T3. Compare α with bootstrap CIs.
- **H4:** Agreement between models on T3 is higher under C2 than C1; added context aligns the models. This is null-tolerant.
- **H5:** C1→C2 rating changes are rule-consistent more often than they are violating. Use a binomial test on the constrained transitions.
- **H6:** Within-model repeatability is higher than between-model agreement.

**Statistics:**
- paired, within-company tests (McNemar, Wilcoxon signed-rank)
- Holm correction within each hypothesis family
- effect sizes (odds ratios, Cliff's δ) with CIs

In METHODS.md, state plainly that this is a **pilot-scale** study (20 companies, 2 repetitions) and that results are exploratory.

**Baseline comparison:** compute every metric for the baseline model separately and add a "Primary panel vs. controlled baseline" table. Report the differences descriptively; do not run significance tests with n = 1 model.

**Reporting checklist:** generate `docs/REPORTING_CHECKLIST.md` that maps each GUIDE-LLM / MI-CLEAR-LLM minimum item to this study:
- model name and identifier
- provider and access channel
- version and date
- system prompt
- user prompt
- temperature and other parameters
- number of runs
- parsing and aggregation
- data-leakage safeguards

Mark each item **met**, **partially met** (Cursor runs: model name only, Cursor version, dates), or **not met** with the reason (Cursor: hidden system prompt, no temperature control). Fill it automatically from the run logs where possible.

---

## 6. Data ingestion

The owner wants to use **existing public data**, not hand-collect data where avoidable.

1. Research and prefer a **structured source**: BRSR XBRL filings on NSE/BSE (machine-readable), or an existing public structured BRSR dataset. Document coverage, licence and fields in `docs/DATA_SOURCES.md`. Build the parser against real files I place in `data/raw/`; do not guess element names.
2. **Fallback:** `data/manual_entry_template.csv` with these columns:
   `company, nse_symbol, sector, fy, indicator, value, unit, boundary, assured, source_url, page_ref`
   Include a validator.
3. **Provenance:** file SHA-256, source URL and retrieval date.
4. **`verify-sample`:** draw a seeded 10% sample and produce a checklist for me to confirm against the original filings, then report the error rate.
5. **Quality validators:**
   - non-negative values
   - renewable energy ≤ total energy
   - waste recovered ≤ waste generated
   - water consumption ≤ water withdrawal
   - flag any 2-year change above ±60%
   - flag boundary changes across years

---

## 7. Database

Implement SQLAlchemy models and export the DDL to `docs/schema.sql`. Tables:
`sector`, `company` (masked code + real name), `report`, `indicator_value`, `kpi_value`, `sector_benchmark`, `sdg_mapping`, `rule`, `condition`, `prompt_template`, `model`, `run` (all fields from §2.5, plus mode cli/manual), `run_company_position`, `judgment` (parsed per-company output), `claim`, `evaluation_result`, `transition_result`, `annotation`, `disagreement_flag`.

---

## 8. CLI (`gauge …`)

`init-db` · `ingest` · `standardize` · `validate` · `verify-sample` · `compute-kpis` · `benchmarks` · `build-rules` · `render` · `freeze` · `run --mode cli|manual|api` · `import-manual` · `parse` · `evaluate` · `stats` · `checklist` · `export` · `dashboard`

`make all-dry` runs the whole pipeline on 2 synthetic sectors × 3 synthetic companies, using a **MockRunner** (deterministic fake JSON with some noise and a few deliberate errors). It must never call Cursor.

---

## 9. Dashboard (Streamlit; reads only from the DB)

1. **Company KPIs:** KPIs, 3-year trends, position against sector benchmarks, quality flags, SDG relevance (with caption), and a masked/real name toggle.
2. **Model reliability scorecard:** per model —
   - T2 accuracy
   - context distortion
   - repeatability
   - agreement with the standard
   - parse-failure rate
3. **C1 vs C2:**
   - rating-shift chart per model
   - transition consistency bars
   - agreement between models in each condition
4. **Disagreement queue:** company-level flags (models disagree on T2, a T2 class flip, a rule violation). Clicking a flag shows the evidence and every model's output side by side.
5. **Annotation:** a labeling UI for non-numeric claims and for the interpretation/ambiguity taxonomy, with 2 annotators and Cohen's κ.
6. **Audit trail:** a searchable log of all runs, with export.

---

## 10. Build order with stop gates

At each **STOP**, summarize what was built, the test results and any open issues, then wait for me.

1. **Scaffold:** repo, config, DB, CLI skeleton, CLAUDE.md, MockRunner, `make test`. **STOP.**
2. **Data pipeline on synthetic data:** loaders, standardization, validators, KPI engine with tests, benchmarks; research the data sources into `DATA_SOURCES.md` and `VERIFY.md`. **STOP** — I will add real data.
3. **Real data:** ingest, quality report, `verify-sample`. **STOP** — I will verify.
4. **Rules and prompts:** T2 and T3 rules, the C1/C2 renderer, and one full sample prompt per condition in `docs/sample_prompts.md`. **STOP** — I will review, then you run `freeze`.
5. **Runner:**
   - check `cursor-agent --help` and the docs, and write `docs/RUNNER.md`
   - implement the cli, manual and api modes
   - test end-to-end with the MockRunner
   - verify on OpenRouter which `:free` models are currently available, and propose the baseline model ID
   - do **one** real smoke test on 2 companies per channel (one Cursor model, one API baseline), after asking me

   **STOP** — I will launch the 16 Cursor runs and the 4 baseline runs.
6. **Evaluation, MSA and statistics:** on mock outputs first, then real ones. Write METHODS.md and the results tables (CSV + Markdown). **STOP.**
7. **Dashboard.** **STOP.**
8. **Paper support:** a notebook that produces every figure and table, and a `docs/RESULTS_SKELETON.md` mapping the tables to hypotheses. No interpretive claims; I write those.

Keep each phase small enough to finish within one usage window of my Claude plan. If a phase is large, split it and say so.

---

## 11. Never claim (in code comments, docs or the dashboard)

- that a model "thinks" or "has a perspective" — say "the model output…"
- that one model is better because its text sounds better
- that BRSR data are fully reliable
- that an SDG mapping shows SDG achievement
- that lower raw emissions means a greener company
- that a model's self-reported justification explains its decision
- that pilot-scale results generalize beyond this sample

---

## 12. README hand-off notes for me

- Install and log in to the Cursor CLI. Fill in the model names in `config/models.yaml` exactly as Cursor lists them.
- Create a free OpenRouter account (no card needed) and put the key in `.env` as `OPENROUTER_API_KEY`, for the 4 baseline runs. The unfunded free tier (about 50 requests/day) is enough.
- My manual steps:
  - put the data files in `data/raw/`
  - confirm the verification sample
  - review the prompts before freezing
  - launch the 16 runs
  - do the annotation (with a second annotator, for κ)
- In the paper's limitations, record:
  - Cursor's agent adds its own hidden system instructions
  - the temperature cannot be controlled for the Cursor runs
  - the backing model versions may change without notice
  - mitigation: a fully controlled open-model API baseline, plus the reporting checklist
  - companies are batched in each prompt
  - the study is pilot-scale

Begin with Phase 1.
