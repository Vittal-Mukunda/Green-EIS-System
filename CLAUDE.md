# CLAUDE.md — "LLM Gauge" Green EIS

Full build spec: [docs/BUILD_SPEC.md](docs/BUILD_SPEC.md) (section numbers like §4.5 below refer to it).
Design decisions in the spec are **final**. If one cannot work for a concrete technical reason, stop and tell the owner; never change it silently.

## 0. Context

**Project:** "Is the LLM a Reliable Gauge? A Green Enterprise Information System for Measurement-System Analysis of Multi-LLM Interpretation of Indian BRSR Sustainability Evidence."
**Owner:** undergraduate Industrial Engineering & Management student; Enterprise Information Systems course project, intended to become a short paper. Pilot-scale, exploratory.

**Tooling and budget (fixed, no paid APIs):**
- Building: Claude Code on the owner's $20 Claude subscription. Work in phases and **stop at every gate** (§10).
- Primary models: owner's $20 **Cursor** subscription via `cursor-agent`, driven by a Python runner. A **manual fallback** (paste prompt files into Cursor chat) must also exist.
- Controlled baseline: **one open-weight model** via a free API tier (OpenRouter `:free`; the spec's `openai/gpt-oss-120b:free` does not exist today (paid only, checked 2026-10-02), so the proposed default is `nvidia/nemotron-3-super-120b-a12b:free`, V-04; fallback Groq free tier). No hidden system prompt, temperature fixed and logged.
- Why the baseline exists: Cursor injects its own system prompt and hides temperature, so Cursor runs cannot meet GUIDE-LLM / MI-CLEAR-LLM minimum reporting items. The API baseline can.

**Pipeline:** ingest BRSR environmental data → standardize → deterministic KPIs, trends, sector benchmarks (= **ground truth**) → render the same evidence into **2 conditions** (C1, C2) → **4 Cursor models × 2 conditions × 2 reps = 16 runs** + **4 baseline runs** = **20 runs**, all study companies batched in each prompt → import, parse, score → management dashboard.

**Critical principle:** models receive *evidence*, never our conclusions. The T2 rule class and all evaluation results are never shown to a model.
**Self-preference control:** Claude models are excluded from the primary panel (optional separate 4-run Claude sensitivity check, never pooled).

**Stack:** Python 3.11+, SQLAlchemy 2.x + SQLite (Postgres-compatible schema), pydantic v2, pandas/numpy, scipy/statsmodels/krippendorff, Streamlit + Plotly, typer, pytest, ruff.

## 2. Hard rules

1. The runner **never** runs the Cursor agent in a project folder. Every run executes in an **empty** `runs/sandbox/` (no code, no data, no `.cursor` rules); prompt text is passed directly.
2. **One fresh session per run**; no shared conversation history.
3. Before writing the runner, read `cursor-agent --help` and Cursor CLI docs. Use only flags that really exist (non-interactive mode, model selection, output format, disabling tools/file edits). Record CLI version + exact command in `docs/RUNNER.md`. If a capability is missing, document it as a limitation; do not fake it.
4. **Explicit model names only**, never "auto". Fail the run if a name in `config/models.yaml` is a placeholder or is not in the CLI's model list (if the CLI has one).
5. **Log per run:** run ID, UTC timestamp, CLI version, model, condition, repetition, seed, exact command, full prompt + SHA-256, raw stdout/stderr, exit code, duration. Save raw output to `runs/raw/{run_id}.txt` **before** parsing.
6. Runs are **resumable and idempotent**: existing successful raw file → skip unless `--force`.
7. Rules and prompt templates are **frozen** (SHA-256 manifest `registry/frozen_manifest.json`) before the first real run; the runner refuses to start if a frozen file changed.
8. **Never invent** data, BRSR field names, XBRL element names, CLI flags or model names. Unverified items get `TODO(verify)` and an entry in `docs/VERIFY.md`.
9. **Company names are masked** in every prompt (e.g. `CEM-03`); the mapping lives only in the DB.
10. Rank/classify **only on intensities and within-sector comparison**, never raw emissions.
11. **Pause between runs** (default 20 s). On a usage-limit error, stop cleanly and resume later.
12. Baseline API runs: key from `.env` (`OPENROUTER_API_KEY` / `GROQ_API_KEY`, gitignored); **only `:free` model IDs** on OpenRouter (fail otherwise); `temperature=0` logged, plus top_p/max_tokens/seed if supported, provider-returned model string, rate-limit headers; send **our** system prompt explicitly (same instructions as the Cursor models, in the system role). If the batch exceeds free-tier limits, split by sector, document it, and apply the same split to all baseline runs.

## 4. Study design (implement exactly)

- **Sample:** Cement, Iron & Steel, IT Services, FMCG; **5 companies per sector (20 total)**, `study.yaml` may raise to 10. Selection: largest by market cap, BRSR filers, complete core indicators for FY2022-23, FY2023-24, FY2024-25. Log every exclusion + reason. Analysis year FY2024-25; earlier years for trends.
- **Core indicators (BRSR Principle 6 essentials; verify exact fields):** revenue from operations; total + renewable energy (GJ); Scope 1, Scope 2 (tCO2e); water withdrawal + consumption (kL); waste generated + recovered (t); reporting boundary; assurance status.
- **Derived KPIs** (deterministic, `Decimal`, ≥5 hand-calculated tests): energy intensity, emissions intensity (S1+S2 per ₹ crore), water intensity, renewable share, waste recovery rate, 2-year % change of each. Sector benchmarks: median/P25/P75 from our sample (small-sample caveat in METHODS.md).
- **Conditions:** **C1** = raw indicators + derived KPIs, FY2024-25 only, Markdown table per company. **C2** = C1 + 3-year intensity trend + sector median/P25/P75; same format. A test must prove every C1 value appears identically in C2. SDG mappings: dashboard only, caption "mapping indicates relevance, not achievement".
- **Task (one combined prompt per run):** per company return JSON `{company_code, t2_class (Leader|Average|Laggard), t3_rating 1-5, t3_confidence 1-5, top_drivers (3 indicator names, ranked), justification (≤40 words, every claim names its indicator), insufficient_evidence (bool)}`; whole response is one JSON array, no text outside it. Prompt says: use only given evidence; assess each company independently. **Company order randomized per run** (seed differs per run); log each position.
- **T2 rule** (`registry/rules/t2_v1.yaml`, frozen): per sector, tertile cut-points on FY2024-25 for emissions intensity (lower better), water intensity (lower better), renewable share (higher better). Best tertile 2 / middle 1 / worst 0; sum 5–6 Leader, 2–4 Average, 0–1 Laggard. Rule text + each sector's cut-points appear in the prompt under **both** conditions, so the correct class is identical in C1 and C2; any C1→C2 change is an **error**.
- **T3 update rule** (`registry/rules/t3_update_v1.yaml`, frozen), per (model, company, rep) C1→C2: trend signal +1 if ≥2/3 core intensities improved ≥5% FY23→FY25, −1 if ≥2 worsened ≥5%, else 0; benchmark signal +1 if better than sector median on ≥2/3 core metrics, −1 if worse on ≥2, else 0. Both +1 (or +1/0) → rating(C2) ≥ rating(C1); both −1 (or −1/0) → ≤; conflicting or both 0 → unconstrained. Label consistent / violating / unconstrained; store signed change.
- **Runs:** primary panel = 4 non-Claude Cursor models (different vendors, names filled by owner on run day, fixed mid-study); run order seeded-random across models and conditions; **rep 2 starts ≥1 h after rep 1**. Baseline = reported **alongside**, never pooled into cross-model agreement; used for a channel check. Optional: Claude sensitivity (4 runs, separate); leave-one-indicator-out extension (12 runs).
- **Evaluation** is rule-based; **no LLM-as-judge anywhere**. Details in §5 of the spec (T2 accuracy, context distortion, repeatability, reproducibility with bootstrap CI, attribute-agreement MSA, T3 update consistency, grounding, position effect, error taxonomy, H1–H6, Holm correction).

## 11. Never claim (code comments, docs, dashboard)

- that a model "thinks" or "has a perspective" — say "the model output…"
- that one model is better because its text sounds better
- that BRSR data are fully reliable
- that an SDG mapping shows SDG achievement
- that lower raw emissions means a greener company
- that a model's self-reported justification explains its decision
- that pilot-scale results generalize beyond this sample

## Working agreements

- **Phase gates (§10):** build one phase, run tests, summarize (built / test results / open issues), **STOP and wait** for the owner. Split a phase if it is too large for one usage window.
- Ask before any real model call (smoke tests in Phase 5) and before spending any quota.
- Match surrounding style; ruff-clean; type hints; tests for every deterministic computation.
- Never touch `data/raw/` contents, `.env`, or `registry/frozen_manifest.json` except through the CLI.

## Phase 4 conventions

- Rules are applied to the DISPLAYED numbers (KPIs and cut-points at 4 significant figures,
  half-even; raw indicators at 6); ties at a cut-point go to the better tertile; T3 signals are
  computed from the displayed numbers too. Do not change a rounding or tie rule after the freeze.
- C2 = the C1 block verbatim + a context table; keep it that way (a test depends on it).
- Prompts depend only on (condition, company order), never on a model name. The frozen manifest holds
  the hash of every planned run's rendered prompt; `freeze --verify` re-renders and compares.
- Previews from candidate companies use `--provisional` and go to `runs/provisional/`, never to the
  registry. Real `build-rules` needs `included` companies (`gauge select`).
- Run Python as `C:\Users\vitta\.venvs\eis-gauge\Scripts\python.exe`; edit anything containing
  backslashes with the Edit/Write tools, not a Bash heredoc (see the memory note).

## Dashboard interface conventions

- Pages call components (`dashboard/components/`); they never write CSS or HTML structure themselves.
  All colour, type and spacing come from the tokens in `dashboard/styles/theme.css`.
- Positions use only the six words in `components/status_badge.POSITIONS`; never "rating", "score",
  "good" or "bad". A data check is never given a rank. Benchmarks are called "study-sample median".
- `st.html` strips inline SVG and drops a whole `<style>` block if the CSS contains tag-like text
  (`<p`, `</`, `<!`); `tests/test_ui_components.py` guards this. Icons are Material Symbols by ligature.
- Page order is `vocab.EIS_VIEWS` (it is the sidebar order). Streamlit module edits need a server restart;
  CSS edits do not.
- AppTest sees `st.html` blocks as `at.get("html")` (`.proto.body`); `tests/test_ui_pages.py` has helpers.

## Environment notes

- Windows 11, PowerShell/Git Bash. `make` and `uv` are **not installed** → `python tasks.py <target>` mirrors every Makefile target (`test`, `lint`, `all-dry`, `ddl`).
- Project lives in OneDrive, so the virtualenv is kept **outside** it: `C:\Users\vitta\.venvs\eis-gauge` (use `...\Scripts\python.exe`). Do not create `.venv/` in the project.
- OneDrive marks the folders it manages **read-only** (Windows then refuses `rmdir`); the dry-run reset
  handles it (`pipeline._clear_readonly_and_retry`). The real SQLite DB also lives in OneDrive: if
  "database is locked" or sync-conflict copies ever appear, pause sync or move the project folder.
- Not a git repository yet (owner has not asked for `git init`).

## Conventions learned so far

- In Bash-tool commands doubled backslashes collapse; use the Edit/Write tools for text with backslashes.
- XBRL unit labels are unreliable (MtCO2e, INR scale): `config/xbrl_overrides.yaml` holds evidenced overrides; the loader refuses unresolved values and unverified taxonomy versions.
- NSE hosts are unreachable from the shell and the browser pane cannot save files: NSE downloads are the owner's.
- KPI formulas live in `config/indicators.yaml` and are executed by `kpi/formula.py` (no `eval`).
- Water intensity is on water **consumption** (owner decision 2026-10-02).
- `docs/VERIFY.md` is the register of unverified items; update it whenever something is guessed.
- Do not scrape NSE/BSE. NSE's Terms of Use (read 2026-10-02) prohibit "systematic or automated data
  collection"; the owner downloads filings by hand (`docs/DOWNLOAD_CHECKLIST.md`). AMFI and SEBI
  public documents may be downloaded. NSE's archive host also times out from this machine.
- The candidate pool's sector assignment is the assistant's judgement, not a data source (V-22).
- Test hand-calculated values as literals; never recompute an expected value with the code under test.

## Status

| Phase | State |
|---|---|
| 1 Scaffold | built, reviewed |
| 2 Data pipeline (synthetic) | built, awaiting owner review |
| 3 Real data | in progress: 20 FY2025-26 filings loaded (gives FY2024-25 + FY2025-26); FY2023-24 XBRL loaded for Shree Cement, UltraTech and JK Cement (2026-10-05); the other 17 FY2023-24 filings are still missing, then `select` |
| 4 Rules and prompts | built except the real freeze: T2/T3 rules, C1/C2 renderer, templates, `build-rules`/`render`/`freeze`, dry run end to end; `docs/sample_prompts.md` awaits owner review (V-28); **`gauge freeze` must not be run on real data until the owner has reviewed it** |
| 5 Runner | built and tested against fakes (fake `agent`, canned runners, mocked HTTP); **never run against the real CLI/API**. Owner steps and open points (V-03, V-04, V-30..V-34) are in `docs/RUNNER.md`; the owner runs `gauge smoke` |
| 6 Evaluation / MSA / stats | built and tested (hand-derived expectations, published reference values for kappa/alpha); `gauge evaluate/stats/export/checklist` run end to end on the dry run; design choices for owner review in V-35/V-36 |
| 7 Dashboard | built and tested with Streamlit AppTest: seventeen pages (twelve evidence pages over the evidence DB, five model views), masked/real toggle, two writes (annotation, data verification), audit trail; data layer in `src/gauge/viewdata.py`. Views are chosen by `dashboard.views` in the study config; `config/study_demo.yaml` + `streamlit_app.py` give the no-login public demo (`docs/DEPLOY.md`, `docs/DEMO_WALKTHROUGH.md`, case for the design in `docs/EIS_JUSTIFICATION.md`). Interpretation layer (positions, data-check policy, readings, what-if, query, comparison, compliance checks) in `src/gauge/viewdata.py`; the twelve evidence pages are in `dashboard/eis_pages.py`, the router and model views in `dashboard/app.py`. Companies show by real name by default (sidebar switch for masked codes). Not yet deployed. V-37..V-52 are open. **Interface redesigned** (2026-10-04, `docs/UI_DESIGN.md`): enterprise shell (grouped sidebar, top bar with search, breadcrumb), design tokens in `dashboard/styles/`, reusable `dashboard/components/`, pages split into `dashboard/eis_*.py`, presentation helpers in `src/gauge/viewdata_ui.py`; no calculation changed |
| 8 Paper support | built: `notebooks/analysis.ipynb` (generated by `scripts/build_notebook.py`, DB only, executed in a test) and `docs/RESULTS_SKELETON.md` |
