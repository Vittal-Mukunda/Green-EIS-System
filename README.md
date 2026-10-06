# LLM Gauge: a Green EIS for measurement-system analysis of multi-LLM BRSR interpretation

Course project (Enterprise Information Systems), intended to become a short paper. It ingests Indian
BRSR environmental data, computes deterministic KPIs and sector benchmarks (the ground truth), shows
the same evidence to several LLMs under two conditions, and scores how reliable the models are as
"gauges". Pilot-scale (20 companies, 2 repetitions) and exploratory.

Design: [docs/BUILD_SPEC.md](docs/BUILD_SPEC.md). Working notes for Claude Code: [CLAUDE.md](CLAUDE.md).

## Status

Everything the study needs before the real model runs is built and tested: the data pipeline, the
rules and prompts, the runner (Cursor CLI, manual and API channels, tested only against fakes, see
`docs/RUNNER.md`), parsing and repair, evaluation and statistics, the dashboard and the analysis
notebook. What remains is yours: the 20 FY2023-24 filings (then `gauge select`), the Cursor setup, the
review of `docs/sample_prompts.md` before `gauge freeze`, the smoke tests, the runs and the
annotation. See the table in CLAUDE.md and the open items in `docs/VERIFY.md`.

## Install (Windows, PowerShell)

The virtualenv lives **outside OneDrive** so thousands of package files are not synced.

```powershell
python -m venv $HOME\.venvs\eis-gauge
& $HOME\.venvs\eis-gauge\Scripts\Activate.ps1
pip install -e ".[dev]"          # or: pip install -r requirements.txt
```

`make` and `uv` are not installed here, so every Makefile target also exists as `python tasks.py`:

| Task | Command |
|---|---|
| Run tests | `python tasks.py test` (or `make test`) |
| Lint | `python tasks.py lint` |
| Whole pipeline on synthetic data, MockRunner only | `python tasks.py all-dry` (or `make all-dry`) |
| Regenerate `docs/schema.sql` | `python tasks.py ddl` |
| Lint + tests + dry run | `python tasks.py check` |

CLI: `gauge --help` (after activating the venv) or `python -m gauge.cli --help`.

## What exists in Phase 1

- `config/`: study, models and indicator configs, validated on load (`src/gauge/config.py`).
- `src/gauge/db/`: SQLAlchemy 2.x schema (the 19 tables of spec §7 plus `quality_flag`), portable to
  PostgreSQL; DDL in `docs/schema.sql` and `docs/schema_postgres.sql`.
- `src/gauge/schemas.py`: the strict pydantic output schema every model response must satisfy.
- `src/gauge/runner/`: run contract, seeded 20-run plan, idempotent logged execution, `MockRunner`.
- `src/gauge/cli.py`: all spec §8 commands.

## What exists in Phase 2

- `ingest/manual.py`: manual-entry CSV validator and all-or-nothing loader with mandatory provenance.
- `ingest/xbrl.py`: generic, hardened XBRL reader and inspector. It knows no BRSR element names; the
  mapping is written in Phase 3 from your real files.
- `standardize/`: exact unit conversion (ambiguous units are rejected, not guessed) and fiscal years.
- `quality/validators.py`: the §6.5 checks, stored as flags.
- `kpi/`: Decimal KPI engine; the formulas in `config/indicators.yaml` are the ones executed.
- `benchmark/`: exact quantiles; sector median, P25, P75 and tertile cut-points.
- `sdg/`: informational SDG relevance mapping (dashboard only; target wordings verified on the UN site).
- `docs/DATA_SOURCES.md`: the data-source research. `docs/VERIFY.md`: open and partly verified items.
- `docs/REFERENCE_FILES.md`: the five official PDFs downloaded into `data/raw/reference/`, with SHA-256.
- `data/reference/candidate_pool.csv`: 35 companies from the AMFI market-cap ranking with a proposed
  sector assignment (regenerate with `python scripts/build_candidate_pool.py`).
- **`docs/DOWNLOAD_CHECKLIST.md`: what you need to download by hand, and how (start here).**

### The data commands

```powershell
gauge init-db                                   # schema + sectors, conditions, models, SDG mapping
gauge ingest --manual data\my_filings.csv --validate-only   # check a CSV; loads nothing
gauge ingest --manual data\my_filings.csv --retrieved-on 2026-10-05
gauge standardize                               # convert to canonical units (originals are kept)
gauge validate                                  # data-quality flags; --strict exits 1 on any error
gauge compute-kpis                              # intensities, shares, 2-year changes
gauge benchmarks                                # needs `included` companies (Phase 3 selection)
gauge ingest --inspect-xbrl data\raw\filing.xml --facts-csv facts.csv   # study a downloaded XBRL file
gauge ingest --xbrl <folder-or-files> --retrieved-on 2026-10-02   # load BRSR XBRL filings (both years in each)
gauge verify-sample                             # seeded 10% sample, auto-checked against PDFs, to confirm by eye
gauge verify-sample --record data/processed/verify_sample.csv   # store your ok/error column
```

Fill the CSV from `data/manual_entry_template.csv`: one row per company, year and indicator, with
`source_url` and `page_ref` on every row. Use the unit exactly as the filing states it (`MWh`, `Mn Lt`,
`INR lakh`, `MT`, ...); the loader rejects units it cannot convert exactly. Do not scrape NSE or BSE:
download filings by hand (`docs/DATA_SOURCES.md`, V-15).

### The rule and prompt commands

```powershell
gauge build-rules --provisional      # preview T2 cut-points from the 20 candidates (runs\provisional\)
gauge render --provisional --condition C1 --sample --out runs\provisional\sample.md   # one full C1 prompt
python scripts\make_sample_prompts.py   # regenerate docs\sample_prompts.md (real C1 + synthetic C2)
gauge build-rules                    # real rules into registry\rules\ (needs included companies)
gauge render                         # every run's prompt into runs\prompts\ with index.csv
gauge freeze                         # SHA-256 manifest of rules, templates and every rendered prompt
gauge freeze --verify                # check nothing has changed since (the runner does this first)
```

Do not run `gauge freeze` until you have reviewed `docs/sample_prompts.md` and the sample is final:
after the first run the freeze cannot change.

### The runner commands (nothing here makes a real call until you launch it)

```powershell
gauge smoke --channel cli --model P1   # ONE real call on a tiny SYNTHETIC prompt; asks first
gauge smoke --channel cli --model P1 --transport stdin   # if the prompt is too long for the command line
gauge smoke --channel api --model B1
gauge run --mode cli [--only P1,P2] [--limit 4]   # Cursor CLI; refuses unless frozen files match
gauge run --mode manual                # prints what to paste where; then: gauge import-manual
gauge run --mode api                   # the free-tier baseline
gauge parse                            # replies -> judgments, parse-failure rate per model
gauge parse --repair --mode cli        # the single repair attempt per run with invalid companies
```

`gauge run` exit code 3 means it stopped early (usage limit, repetition gap, repeated failures):
run the same command later and it resumes.

### The dashboard and the notebook

```powershell
gauge dashboard                       # Streamlit, twelve evidence pages (home, companies, sectors,
                                      #   metrics guide, compare, query and chart, scorecard, compliance
                                      #   check, data quality, sources, verification, about) then the model views
                                      #   (scorecard, C1 vs C2, disagreement queue, annotation, audit trail).
                                      #   It writes two things: annotations and data verifications.
python scripts\build_notebook.py      # regenerate notebooks\analysis.ipynb (tables and figures, DB only)
$env:GAUGE_CONFIG = "config/study_dry.yaml"   # run the notebook on the synthetic dry run instead
```

A public demo of the evidence views (no login) is described in `docs/DEPLOY.md`; the tour for whoever
evaluates it is `docs/DEMO_WALKTHROUGH.md`. The case for the design, with what is and is not
shown, is `docs/EIS_JUSTIFICATION.md`.

The notebook needs Jupyter, which is not installed by default: `pip install jupyterlab`. It saves every
table as CSV and every figure as HTML under `data\processed\results\notebook\`.
`docs\RESULTS_SKELETON.md` maps those tables to the hypotheses, with places for your own text.

### The evaluation commands (they only read the database; no model is called)

```powershell
gauge evaluate          # score judgments against the rules: claims, C1->C2 transitions, flags, metrics
gauge stats             # hypotheses H1-H6 (Holm), rating-shift test, position effects
gauge export            # CSV tables and RESULTS.md in data\processed\results\
gauge checklist         # docs\REPORTING_CHECKLIST.md filled from the run logs
```

`gauge all-dry` runs every stage on synthetic data with the mock runner (17 stages); its outputs go
to `dry\` and carry a MOCK banner.

## Hand-off notes for the owner

1. **Cursor CLI.** Install and log in to the Cursor command-line agent (its command is `agent`; the
   runner also tries `cursor-agent`). Then put the exact model names Cursor lists into
   `config/models.yaml` (P1-P4; non-Claude; different vendors where possible). They must not change
   mid-study. Real runs refuse to start while a name is a placeholder. The full order of steps, and
   what is and is not verified about the CLI, is in `docs/RUNNER.md`.
2. **Baseline API key and model.** Create a free OpenRouter account (no card) and put the key in `.env`
   as `OPENROUTER_API_KEY` (copy `.env.example`). The spec's default `openai/gpt-oss-120b` is paid-only
   on OpenRouter today, so the default in `config/models.yaml` is now
   `nvidia/nemotron-3-super-120b-a12b:free` (decision V-04). Only `:free` IDs are accepted and the ID is
   checked against OpenRouter's live list before each start.
3. **Your manual steps, in order:**
   - download the 20 FY2023-24 filings (`docs/DOWNLOAD_CHECKLIST.md`), then `gauge ingest`,
     `gauge standardize`, `gauge validate`, `gauge compute-kpis`, `gauge select`, `gauge benchmarks`
   - confirm the verification sample (`gauge verify-sample`)
   - review `docs/sample_prompts.md` and the decisions in V-28, then `gauge build-rules`, `gauge render`
     and `gauge freeze`
   - install Cursor, fill the model names, run the smoke tests (`gauge smoke`)
   - launch the runs (`gauge run`), then `gauge parse`, `gauge evaluate`, `gauge stats`, `gauge export`
   - do the annotation in the dashboard (with a second annotator, for Cohen's kappa)
4. **Decisions waiting for you:** see `docs/VERIFY.md` (rows marked `owner`), in particular V-04, V-23,
   V-27 to V-30, V-33 to V-36.
5. **Limitations to record in the paper:**
   - Cursor's agent adds its own hidden system instructions
   - the temperature cannot be controlled for the Cursor runs
   - the backing model versions may change without notice
   - mitigation: a fully controlled open-model API baseline, plus the reporting checklist
   - companies are batched in each prompt
   - the study is pilot-scale

## OneDrive note

This folder is synced by OneDrive. OneDrive marks synced folders read-only, which blocks deleting
them on Windows (handled in the dry-run reset). SQLite files can also hit locking or conflict-copy
problems under sync; if you ever see `database is locked`, pause OneDrive sync or move the project
outside OneDrive.

## Not a git repository yet

Nothing has been committed. When you want version control: `git init`, then commit. `.gitignore` already
excludes `.env`, `data/raw/`, `dry/` and the sandbox contents, and keeps raw model outputs and rendered
prompts tracked, since they are study data.
