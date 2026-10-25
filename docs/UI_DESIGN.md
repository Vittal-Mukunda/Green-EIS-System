# Interface design (GreenEIS)

The look and the building blocks of the dashboard, and the rules they keep. The design system, the shell
and the reusable components were carried over from the previous project (archive tag `archive/llm-gauge`);
the pages, the vocabulary and the data behind them are new. It is a presentation layer: no calculation
lives here.

## 1. What the interface is for

A small unit's manager enters a month of data and sees, with as little effort as possible:
**how much, how far to believe it, where it comes from, what it costs, and what a change would do.**
The chain is Data entry, Summary, Hotspots, What-if, Report. A separate group, Study, shows whether the
trust score itself holds up; Reference lists every factor and its source.

## 2. Principles the interface keeps (and tests check)

| Principle | How it shows |
|---|---|
| Every number says how well it is known | Each activity carries a data-class badge (Measured, Estimated, Default); the Summary leads with the trust index and a range |
| Estimates, not certificates | The standing note ("GreenEIS estimates; it does not certify") ends every page and every report |
| Placeholders are called placeholders | The trust scores and ranges are labelled indicative wherever they appear (`alerts.PLACEHOLDER_NOTE`) |
| Example data is never mistaken for real data | An amber status chip, an "Illustrative example" sidebar block and a banner on every unit page while the example is loaded |
| Synthetic study results are never mistaken for findings | A red banner on the Study results page and a `synthetic` flag in the result file |
| Nothing is hidden to look tidier | A row that cannot be calculated is left out of the totals and named in a red callout; a missing data class is treated as Default and says so |
| Provenance stays visible | Factors and method lists every factor with its source, year and verification status |
| Colour is never alone | Every badge carries a word and an icon; chart colours are explained in a caption |
| Pages call components | A test fails if a page module writes `<style>`, `unsafe_allow_html` or HTML structure |

## 3. Visual language

Neutral foundation, deep forest green as an accent only (active navigation, the product mark), a restrained
blue for information, amber for "look at this", muted red for a failed check. Data classes use green
(Measured), blue (Estimated) and amber (Default) in badges and charts.

- **Type**: Inter (system fonts as fallback). Application name 15 px, page title 24 px, section heading
  15 px, card heading 13.5 px, KPI number 26 px, table text 13 px, metadata 12 px, labels 10.5 px caps.
- **Density**: tables are compact (36 px rows), cards are used for things that are units (a KPI), not to
  wrap every section; sections are separated by a rule and a heading.
- **Motion**: hover and focus transitions only (140 ms). `prefers-reduced-motion` switches them off.
- **Icons**: one family, Material Symbols (the font Streamlit already loads), used by ligature name.
  There are no emoji in the interface (a test checks).

## 4. Where things live

```
dashboard/
  app.py                  entry: page config, styles, shell, router, footer note
  state.py                session state, the entry table, table -> activities, aggregation, Context
  vocab.py                page names in sidebar order, page notes, slug
  pages_unit.py           Data entry, Summary, Hotspots, What-if, Report
  pages_study.py          Study results (reads outputs/study*.json)
  pages_reference.py      Factors and method, About
  components/             reusable pieces (no page knows any CSS or HTML structure)
    app_shell.py            loads the stylesheets, draws sidebar + top bar
    sidebar.py              brand, grouped navigation, current-unit block, an `extra` hook for controls
    topbar.py               brand, page search, data status chip, help
    page_header.py          breadcrumb, title, scope box; GROUPS (the sidebar groups)
    status_badge.py         badges, data-class badges, trust-band badges, status marks
    kpi_card.py             the KPI strip
    data_table.py           plain tables (escaped cells, numeric alignment, name cell with a badge)
    alerts.py               callouts, toast, the standing notes
    empty_state.py          "nothing here yet" states
    charts.py               Plotly template and palette
    navigation.py           open_page, link_button
    format.py               number formatting
    icons.py, markup.py
  styles/
    theme.css               tokens (colour, type, spacing, radius, shadow, heights), base type
    layout.css              shell, sidebar, top bar, page header, grids, responsive rules
    components.css          components and the restyled Streamlit widgets
.streamlit/config.toml    native theme (dataframes, charts, widgets) in the same tokens
```

Some CSS in `components.css` styles components that no longer exist (benchmark card, exception list,
movement bars, provenance chain, evidence card). It is harmless and kept so the old components can be
restored from the archive tag; remove it if it is never reused.

To add a page: write a function `page(ctx)` in a `pages_*.py` module that starts with `page_header(...)`,
register it in `app.py`'s `PAGE_FUNCTIONS`, and add its name to `vocab.PAGES` (display order),
`vocab.PAGE_NOTES`, `components/icons.PAGE_ICONS` and the right group in `components/page_header.GROUPS`.

## 5. How the shell works (and the traps)

- **Navigation is a real `st.radio`** in the sidebar (keyboard and screen-reader friendly, and its state
  is what `?page=` reads and writes). CSS turns it into a grouped list. Group headings and icons are
  generated per page by `sidebar.nav_css`, because CSS cannot know which option is which page.
- **The top bar is a keyed container** (`eis-topbar`) made sticky on Streamlit's layout wrapper. Its search
  only navigates between pages. There is no user system, so no account menu.
- **`st.html` sanitises**: it removes inline SVG and removes a whole `<style>` block if the CSS text
  contains anything that looks like an HTML tag (a `<p>` in a CSS comment once removed the entire
  design). A test fails if a stylesheet contains `<` followed by a letter, `/` or `!`.
- **`st.markdown` blocks carry a negative bottom margin** in Streamlit; `theme.css` resets it.
- **`st.data_editor` loses or doubles edits if its output is fed back as its input.** `state.py` keeps an
  immutable `bases` table per period (what the editor is given) and a separate `periods` table (what the
  editor returned and what every page reads); on a change the page stores the edit and reruns once so the
  sidebar and other pages never lag. Loading a CSV bumps `editor_version`, which is part of the editor key.
- **Plotly `add_hline` on a secondary axis** syncs the axis ticks to the primary and mislabels them. Draw
  reference lines as traces (see the Pareto chart in `pages_unit.hotspots`).
- Stylesheets are read on every run, so a CSS edit shows on the next rerun. **Python module edits need the
  Streamlit server restarted.**

## 6. Responsive behaviour

The content column is capped at 1360 px and centred. At 1280 px the gutters tighten; under 1100 px the
top bar's subtitle is hidden; under 1000 px grids become two columns; under 760 px the top bar scrolls away
instead of staying sticky; under 640 px everything is one column. Wide tables scroll inside their own frame
and the first column stays in view; the page itself never scrolls sideways. The sidebar collapses with
Streamlit's own control.

## 7. Verified, and known limits

- Run in the Browser pane (Chromium) on 2026-10-25: Data entry, Summary, Hotspots and What-if were
  exercised, including editing a table cell (Summary then showed 40.42 tCO2e for 20,000 kWh, as computed
  by hand) and adding a scenario. All eight pages are also covered by Streamlit's AppTest.
- Not tested in Firefox or Safari, on a phone, or with a screen reader. Every control is a native
  Streamlit widget, but tab order was not audited page by page.
- The data table is a canvas grid: it cannot be driven by simple clicks in automated tests, so row
  editing is verified by hand, not by AppTest.
- No dark theme. All colour is in `theme.css`, so one is possible, but it was not built or checked.
- Inter loads from Google Fonts; offline hosts show system fonts.
- The styling relies on Streamlit's `data-testid` attributes; re-check the pages after an upgrade.
- Entered data live in the browser session only. A refresh loses them; the Data entry page offers a CSV
  download and upload to keep and restore them.
