# CLAUDE.md — GreenEIS

## 0. Context

**Project 8, Industrial Engineering & Management / Enterprise Information Systems course.** Owner is an
undergraduate student; the work is meant to become a short paper. The previous project ("LLM Gauge", BRSR
multi-LLM measurement-system analysis) was rejected by the teacher and **discarded on 2026-10-25**. It is
preserved only as the git tag `archive/llm-gauge` (code and tests; the downloaded filings were deleted and
are not recoverable from git). Do not reuse, port or cite anything from it unless the owner asks.

**GreenEIS:** a lightweight web system through which a small or informal Indian manufacturing unit enters
monthly energy, fuel and cost data and gets: emissions (IPCC-style, Indian factors), a **trust score for
each number** (measured / estimated / default), hotspots, an emissions-to-rupees cost link, a what-if
simulator, and a one-page report. Source of truth for the evidence and the proposed design:
[docs/reference/GreenEIS_Research_and_Design_Reference.docx](docs/reference/GreenEIS_Research_and_Design_Reference.docx)
(sections cited as "ref §n"; its `[S#]` labels are its Source Register, §11).

**The stated gap** (ref §5): no firm-level, regularly updated, validated fuel/energy data exists for India's
informal manufacturing sector, and national estimates carry unquantified uncertainty (CSTEP 2018 calls for
"a transparent monitoring system to record fuel consumption by various industries in the informal sector";
CEEW 2018 calls for validated informal-sector data). The owner should confirm which paper's statement is
the one the project cites.

## 1. Decisions taken with the owner (2026-10-25)

- **Contribution is narrow:** the research question centres on the trust score: do the measured / estimated
  / default labels predict the error of a unit's footprint and the stability of its hotspot ranking, and does
  improving data in order of hotspot size beat the alternatives? Hotspots, cost link, what-if and report are
  supporting modules, not separate claims. Question, hypotheses H1-H5 and analysis: `docs/RESEARCH_DESIGN.md`.
- **Data:** intended source was real unit-level data from public BEE SME energy-audit reports (Pali textile,
  Indore food, Ludhiana forging); **not obtainable today** (V-08). `docs/ASI_OPTION.md` proposes ASI factory
  microdata for calibration, with BEE or SAMEEKSHA data for worked cases. Waiting on the owner. Synthetic data
  only to exercise code, always labelled. No factory access is assumed.
- **Frontend is kept** (design system, components, shell); the pages are new.
- Novelty must not be overclaimed: pedigree-matrix data quality (Weidema; ecoinvent), commercial
  data-quality-to-uncertainty tools (e.g. Verso Climate Hub), SME cost/emissions scenario tools (Zocca et
  al. 2018) and Indian MSME calculators (IIMB, LUME, CarbonTrack) exist. The defensible contribution is the
  combination, applied to Indian informal-sector fuel data and validated; say "we found no tool that
  combines all three", never "first".

## 2. Hard rules

1. **Never invent** data, emission factors, NCVs, grid factors, field names or citations. Unverified items
   get `TODO(verify)` and an entry in `docs/VERIFY.md`.
2. Every factor is stored with **value, unit, source label and year**; units are explicit everywhere
   (CSTEP's tables mislabel kg/TJ as "kt/TJ"; see ref §4.3). Calculation uses `Decimal`.
3. The trust-score values (1.0 / 0.6 / 0.3) and uncertainties (±5% / 25% / 50%) are **uncalibrated design
   choices** (ref §6.5). Present them as indicative; calibrate against the GHG Protocol uncertainty
   guidance / pedigree matrix and run a sensitivity analysis before reporting them as results.
4. Test every deterministic computation with **hand-calculated literals** (ref §7 gives a worked example:
   38.97 tCO2e, trust index 0.72, ±12.9%); never recompute an expected value with the code under test.
5. Retrieved sources were often abstracts only (ref §11 notes this). Read the original before quoting.
6. Report discrepancies in published sources as findings to verify (CSTEP: furnace oil from 2012-13, naphtha
   in all years, LPG 2015-16), never correct them silently.
7. The system **estimates, it does not certify**. Never claim: certified or audited emissions; that the
   trust score is scientifically calibrated; that a default or sector benchmark is the unit's own data;
   that results generalise beyond the cases studied; that lower raw emissions mean a greener unit.
8. No paid APIs. No scraping of sites whose terms forbid it.
9. **No threshold, proxy rule or profile may change after seeing results.** If one must, log it with the
   date and reason in `docs/RESEARCH_DESIGN.md` §10 and rerun everything.

## 3. Working agreements

- **Phase gates:** build, run tests, summarise (built / test results / open issues), stop for review. On
  2026-10-25 the owner waived per-phase approval ("complete whatever you can, no need to ask permission")
  for everything that does not depend on real data; the owner's own steps are in `docs/STUDY_RUNBOOK.md`.
  Still ask before spending quota, creating accounts, accepting terms or sharing anything outside the
  project. Downloads of public documents were pre-approved once (six files); ask again for anything new.
- Match surrounding style; ruff-clean; type hints. Owner wants autonomous progress: do everything
  possible, list only what truly needs them.
- Python is `C:\Users\vitta\.venvs\eis-gauge\Scripts\python.exe` (venv kept outside OneDrive; do not create
  `.venv/` in the project). Windows 11; `make` and `uv` are not installed. Tests: `python -m pytest`
  (`pythonpath = src` is configured, no install needed). App: `streamlit run dashboard/app.py`.
- Edit text containing backslashes with the Edit/Write tools, not a Bash heredoc. The repo is LF-only:
  scripted edits must write bytes, not `write_text`.
- The project is in OneDrive: if sync-conflict copies appear, pause sync.
- Streamlit caches imported page modules: restart the preview server after editing a `.py` file; CSS edits
  apply on the next rerun.

## 4. Code map

```
src/greeneis/
  factors.py       factor library loader (value, unit, source, year, status; refuses anything without them)
  data/fuels.csv, grid.csv   the factors (CSTEP 2018 Tables 2-4; CEA v20.0 Table S)
  engine.py        Decimal calculator: Activity -> energy, CO2, CH4, N2O, CO2e, flags
  validation.py    recompute CSTEP Table 8 from Table 7; flag disagreements, never correct
  trust.py         trust index, uncertainty (placeholders), bands, variance contributions
  hotspot.py       Pareto, vital few, cost link
  whatif.py        activity change / fuel switch / electricity shift; abatement cost
  recommend.py     rule library (ref Table 6.4) with sources and cautions
  report.py        one-page Markdown report with the standing method note
  study/           cases.py (input shape), proxies.py (leave-one-out), outcomes.py (profiles, H5),
                   analysis.py (H1-H5, cluster bootstrap, Holm), asi.py (ASI reader and case table),
                   synthetic.py, run.py (CLI: --source synthetic | csv | asi; --only-sector for exploratory cuts)
dashboard/         the interface (see docs/UI_DESIGN.md)
tests/             130+ tests; hand-worked literals; see the docstring at the top of each file
docs/              FINDINGS, DATA_TO_COLLECT, RESEARCH_DESIGN, RESULTS_ASI_2023-24, PHASE1_SPEC,
                   DATA_INVENTORY, ASI_OPTION, STUDY_RUNBOOK, VERIFY, UI_DESIGN
outputs/           gitignored except the three aggregate ASI 2023-24 result files (no factory rows)
C:/Users/vitta/greeneis-data/asi/ASI24m.TXT   the 610 MB ASI file, kept OUTSIDE the OneDrive project; terms unread
```

## 5. Interface conventions

- Pages call components (`dashboard/components/`); they never write CSS or HTML structure (a test checks).
  All colour, type and spacing come from the tokens in `dashboard/styles/theme.css` (mirrored in
  `.streamlit/config.toml`).
- Icons are Material Symbols by ligature; no emoji anywhere (a test checks).
- `st.html` strips inline SVG and drops a whole `<style>` block if the CSS contains tag-like text
  (`<p`, `</`, `<!`); keep CSS free of them.
- Example data and synthetic study results must always be labelled as such on the page.
- Traps and how the shell works: `docs/UI_DESIGN.md` section 5.

## 6. Status

| Part | State |
|---|---|
| Reset | done 2026-10-25: old project archived (tag `archive/llm-gauge`) and deleted; the interface layer kept |
| Design | `docs/RESEARCH_DESIGN.md` (RQ, H1-H5, threats; H3 revised before any data, §10) approved 2026-10-25 |
| Factor library, engine | built; hand-checked against ref §7 and CSTEP; grid factor verified against CEA v20.0 (V-01) |
| Validation | all 56 CSTEP Table 8 cells recomputed: 43 match, 13 flagged (furnace oil 2012-13 on, naphtha all years, LPG 2015-16); causes unknown (V-06, V-22) |
| Trust, hotspots, cost, what-if, recommendations, report | built and tested; trust values are placeholders (V-11) |
| Study harness H1-H5 | built and tested; **run on real data (ASI 2023-24) on 2026-10-25**, exactly as pre-specified: all five supported, with caveats (H5 rests on 67 factories, H3 is largely structural, pooled results are 90% electricity); see `docs/RESULTS_ASI_2023-24.md` |
| Dashboard | eight pages on the kept design system; verified in the browser and by AppTest |
| Data gate (1a) | **met for one year**: the ASI 2023-24 file is public and was downloaded (V-18: terms still unread). BEE unit audits remain unavailable (V-08); the Wayback copies are rate-limited (V-36) |
| Sector and data plan | decided 2026-10-26: primary sector textile wet processing (NIC 13), bricks as motivating case; list of data to collect in `docs/DATA_TO_COLLECT.md`; consolidated findings in `docs/FINDINGS.md` |
| Textile cut (exploratory) | run 2026-10-26 as declared in RESEARCH_DESIGN §10: H1-H3 supported, H4 not supported (100 factories), H5 insufficient data (5); `outputs/study_asi_2023-24_explor_nic13.json` |
| Repository | `main` replaced by the GreenEIS tree on 2026-10-26 (old LLM Gauge files removed from the tree; kept as tag `archive/llm-gauge`, pushed) |
| Real-data follow-up | needs the owner: teacher's view on ASI, the portal's terms, free login for 2022-23 and 2021-22 (held-out years), per-fuel calibration (`docs/STUDY_RUNBOOK.md` section A) |
