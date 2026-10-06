# Interface design (Green EIS)

This is the design of the dashboard's interface: what it looks like, how it is built, and the rules it
must keep. It is a presentation layer. Nothing here changes a calculation, a validation rule, a
benchmark, a ranking rule or a verification rule; those live in `src/gauge/` and are unchanged.

## 1. What the interface is for

> The chart is not the product. The chain of assurance behind the chart is the product.

The path a reader should be able to follow with as little effort as possible:

```
Executive overview -> Sector -> Company -> KPI -> Study-sample benchmark -> Underlying figure
-> Validation status -> Source filing -> SHA-256 fingerprint -> Human verification
```

Every page has a way onward along that path (a button, a link or a search), and the evidence is never
hidden to make a page tidier.

## 2. Principles the interface keeps (and tests check)

| Principle | How it shows |
|---|---|
| Never rank raw emissions | Every position is on an intensity or a share; raw totals appear only as "figures as reported" with a warning |
| A data check is not a ranking | Chip and cell say "Data check", never a rank; the exception list says "a figure to verify, not a finding that a company misreported" |
| "No clear difference" | Shown when a sector's values lie within 1% of their median (the existing rule); no rank is manufactured |
| Positions are not ratings | Only six words: Better third, Middle third, Weaker third, No clear difference, Data check, Too few to place. Never "rating", "score", "good" or "bad" |
| Provenance stays visible | Company page has an Evidence quality card; Sources and filings draws the whole chain; the register and verification pages link to it |
| No language model on evidence pages | Readings come from the fixed templates in `viewdata.py`; the About page says so |
| Benchmarks are the study sample | "Study-sample median", "P25 to P75"; never "industry benchmark" except to say it is not one |
| Missing or unverified data is shown | "not available", "not yet reviewed", "Data unavailable", "No filing is loaded for FY", "not in the filing data" |
| Monitoring, not law | Compliance page opens with "Monitoring view, not a legal finding" and avoids "breach" language |
| Colour is never alone | Every chip, cell and status has a word; statuses also have an icon (check, warning, cross) |

## 3. Visual language

Neutral foundation, deep forest green as an accent only (active navigation, the product mark, links to
evidence), a restrained blue for information, amber for "look at this", muted red for a failed check.

- **Position colours are one blue ramp** (dark, mid, light) so order shows without a good/bad colour.
  A data check is amber with a dashed outline; "no clear difference" is hatched grey.
- **Type**: Inter (system fonts as fallback). Application name 15 px, page title 24 px, section heading
  15 px, card heading 13.5 px, KPI number 26 px, table text 13 px, metadata 12 px, labels 10.5 px caps.
- **Density**: tables are compact (36 px rows), cards are used for things that are units (a KPI, a
  sector), not to wrap every section; sections are separated by a rule and a heading.
- **Motion**: hover and focus transitions only (140 ms), and a thin progress line while the app is
  running. `prefers-reduced-motion` switches them off.
- **Icons**: one family, Material Symbols (the font Streamlit already loads), used by ligature name.
  There are no emoji in the interface (a test checks).

## 4. Where things live

```
dashboard/
  app.py                  entry: page config, styles, shell, router, model views
  eis_pages.py            Home + the page registry (EVIDENCE_PAGES)
  eis_analysis.py         Sectors, KPI scorecard, Companies, Compare, Query and chart
  eis_assurance.py        Compliance check, Data quality register, Sources and filings, Verification
  eis_reference.py        Metrics guide, About
  eis_common.py           Ctx, header, section, legend, shared helpers
  components/             reusable pieces (no page knows any CSS or HTML structure)
    app_shell.py            loads the stylesheets, draws sidebar + top bar
    sidebar.py              brand, grouped navigation, pilot dataset block, names switch
    topbar.py               brand, global search, dataset status, help
    page_header.py          breadcrumb, title, scope box
    status_badge.py         badges and position chips (the six words)
    kpi_card.py             dataset strip, chain strip, KPI profile card
    benchmark_card.py       study-sample median / P25 / P75 per sector
    comparison_table.py     scorecard matrix and side-by-side comparison
    data_quality_table.py   exception list, movement bars, audit register, compliance matrix
    provenance.py           the traceability chain
    evidence_card.py        evidence-quality card and grouped checks
    alerts.py               callouts, toast, the three standing notes
    empty_state.py          "nothing here yet" states
    filters.py              year picker, pagination
    charts.py               Plotly template, band colours
    navigation.py           callbacks that move between pages
    icons.py, markup.py, people.py
  styles/
    theme.css               tokens (colour, type, spacing, radius, shadow, heights), base type
    layout.css              shell, sidebar, top bar, page header, grids, responsive rules
    components.css          components and the restyled Streamlit widgets
src/gauge/viewdata_ui.py  presentation helpers over the evidence DB (register rows, source trace,
                          sector summary, formulas); no model, no new rule
.streamlit/config.toml    native theme (dataframes, charts, widgets) in the same tokens
```

To add a page: write a function in one of the `eis_*.py` modules that starts with `header(...)`, add it
to `EVIDENCE_PAGES`, and add its name to `vocab.EIS_VIEWS` (display order), `vocab.VIEW_NOTES`,
`components/icons.PAGE_ICONS` and `components/page_header.GROUPS`.

## 5. How the shell works (and the traps)

- **Navigation is a real `st.radio`** in the sidebar (keyboard and screen-reader friendly, and its state
  is what `?page=` reads and writes). CSS turns it into a grouped list. Group headings and icons are
  generated per page by `sidebar.nav_css`, because CSS cannot know which option is which page. The
  options are in display order, which is why `vocab.EIS_VIEWS` follows the sidebar's groups.
- **The top bar is a keyed container** (`eis-topbar`) made sticky on Streamlit's layout wrapper. Its
  search is a `st.selectbox` that only navigates (page, sector or company); it needs no query language.
  There is no user system in this application, so the top bar has no account menu.
- **`st.html` sanitises**: it removes inline SVG and removes a whole `<style>` block if the CSS text
  contains anything that looks like an HTML tag (a `<p>` in a CSS comment once removed the entire
  design). A test fails if a stylesheet contains `<` followed by a letter, `/` or `!`.
- **`st.markdown` blocks carry a negative bottom margin** in Streamlit; `theme.css` resets it, or text
  blocks overlap.
- **Original wording is kept where a test or the scope box depends on it**: every page's first two
  markdown blocks are "What this page shows." and "What is being compared." (the scope box restyles
  the bold lead-in as a label).
- **Sortable, exportable tables** stay as `st.dataframe` (themed through `config.toml`), inside a
  "Sortable table and export" expander where a styled HTML view is the primary view.
- Stylesheets are read on every run, so a CSS edit shows on the next rerun. Python module edits need
  the Streamlit server restarted.

## 6. Responsive behaviour

The content column is capped at 1360 px and centred (1920 and 1440 px screens). At 1280 px the gutters
tighten and five-column grids become three. Under 1000 px grids become two columns and the split
layouts stack; under 640 px everything is one column. Wide tables scroll inside their own frame and
the first column stays in view; the page itself never scrolls sideways. The sidebar collapses with
Streamlit's own control.

## 7. Not done, and known limits

- No dark theme. The tokens make one possible (all colour is in `theme.css`), but it was not built or
  checked.
- Tested in Chromium (the Browser pane) and Streamlit's AppTest. Not tested in Firefox or Safari, on a
  phone, or with a screen reader. Keyboard focus rings are styled and every control is a native
  Streamlit widget, but tab order was not audited page by page.
- Inter loads from Google Fonts; offline hosts show system fonts.
- The styling relies on Streamlit's `data-testid` attributes; re-check the pages after an upgrade
  (see V-52 in `docs/VERIFY.md`).
- The Plotly charts use the product template but keep Plotly's own hover and zoom controls.
- Model views (scorecard, C1 vs C2, queue, annotation, audit trail) take the new shell, header and
  widget styling but were not redesigned page by page.
