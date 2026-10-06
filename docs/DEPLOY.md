# Deploying the EIS demo

The demo is the evidence half of the system (the twelve evidence pages) running over a snapshot of
the database. It needs no login, no API key and no model. What it offers is set by
`config/study_demo.yaml`; the walkthrough for whoever evaluates it is `docs/DEMO_WALKTHROUGH.md`.

Hosting facts in this file (Streamlit Community Cloud's behaviour) were not checked against its current
documentation in the session that wrote it: see V-38 in `docs/VERIFY.md` and confirm them at deploy time.

## What is deployed, and what is not

| Deployed (in the repository) | Not deployed |
|---|---|
| `streamlit_app.py` (the entry point), `dashboard/`, `src/gauge/` | `data/raw/` (the filings; gitignored) |
| `config/` | `.env` (gitignored; the demo needs no keys) |
| `data/demo/gauge_demo.db`, the snapshot | model runs and human annotations (stripped from the snapshot) |

Anything in the repository that is not gitignored becomes public if the repository is public. That
includes `docs/` and `data/processed/gauge.db`, the working database.

## 1. Load the data first

The demo is only as complete as the working database. Before deploying, finish the download steps in
`docs/DOWNLOAD_CHECKLIST.md`, then run `gauge ingest`, `standardize`, `validate`, `compute-kpis`,
`select` and `benchmarks` on the real data, with the owner reviewing the selection. (`python tasks.py
all-dry` builds synthetic data and is not part of this.) Run `gauge verify-sample` and resolve what it
finds before presenting the figures as checked.

## 2. Build the snapshot

```bash
C:\Users\vitta\.venvs\eis-gauge\Scripts\python.exe scripts/make_demo_snapshot.py
```

It copies `data/processed/gauge.db` to `data/demo/gauge_demo.db` (the source is only read), removes model
runs and annotations, and prints row counts. It refuses to write an empty snapshot and warns if any text
column holds a local path. Rebuild it whenever the working database changes, then commit and push.

## 3. Preview it locally

```bash
C:\Users\vitta\.venvs\eis-gauge\Scripts\streamlit.exe run streamlit_app.py
```

This is exactly what the host will run. Open the five views and check them against the walkthrough.

## 4. Put it on GitHub and Streamlit Community Cloud

The project is not a git repository yet.

```bash
git init
git add .
git commit -m "LLM Gauge Green EIS"
```

Push to a new GitHub repository, then in Streamlit Community Cloud choose **New app** and set:

- Repository and branch: yours.
- Main file path: `streamlit_app.py`
- Advanced settings, Python version: **3.12**. The `.python-version` file records this, but the host's
  setting is what counts (V-38).
- Secrets: none.

`requirements.txt` installs everything, including test-only packages; the app itself needs only the
runtime ones. That is slower to build, not wrong.

## 5. After it is live

- Open the URL in a private window (no login should appear) and walk the steps in
  `docs/DEMO_WALKTHROUGH.md`.
- Record one verification, then reload: it is still there. Restart the app from the host's dashboard: it
  is gone. That is the intended behaviour of a shared demonstration copy.
- Free apps sleep after a period of inactivity and take a little while to wake. Open it a few minutes
  before the evaluator does.

## If a view is empty

| You see | Cause | Fix |
|---|---|---|
| "Database not found" | the snapshot is missing from the repository | run step 2 and commit `data/demo/gauge_demo.db` |
| Sector bars all grey, "Sector medians appear once..." | benchmarks not computed | `gauge select`, then `gauge benchmarks`, rebuild the snapshot |
| Many `missing_indicator` flags | years not yet loaded | load the FY2023-24 filings, rebuild the snapshot |
| `ModuleNotFoundError: gauge` | the app was started from a copy that lost `src/` | the repository must contain `src/gauge` |
