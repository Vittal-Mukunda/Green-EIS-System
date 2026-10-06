# Green EIS: a ten-minute tour

**What you are looking at.** A system that turns the sustainability reports (BRSR) that large listed
Indian companies file with the regulator into comparable, traceable environmental metrics, checks them,
and lets you explore, compare and query them. It covers 20 companies in four sectors (Cement, Iron &
Steel, IT Services, FMCG). Nothing here needs a login.

**The layout.** A left sidebar groups the pages (Overview, Analysis, Assurance, Reference) and shows the
pilot dataset at the bottom. A top bar has a search that opens a page, a sector or a company, the status
of the dataset, and a help button. Every page opens with a breadcrumb, its title, and the same scope box:
what the page shows, what is being compared, and how to read it. Each page has its own address, for
example `?page=compare-companies`. Companies are shown by their real names; the switch in the sidebar
gives the masked codes the models saw. Every number carries its unit. The design is described in
`docs/UI_DESIGN.md`; the case for it is in `docs/EIS_JUSTIFICATION.md`.

## The tour

| # | Page | Do this | You should see |
|---|---|---|---|
| 1 | **Home** | Read the **Needs attention** and **What changed** panels, then the chain under **Can I trust the numbers?** | The size of the pilot, the figures that fail a data check (a figure to verify, not a verdict), the largest year-on-year moves, and the chain of assurance: filings, standardised figures, validation, computed KPIs, human checks. |
| 2 | **Sectors** | Pick **Cement**, then a metric such as **Emissions intensity**. Look at the three tabs. | A card per sector with the study-sample median and P25 to P75 of every metric, a description of the sector, a chart of its companies against that median, a table with units and ranks, lines over time, and what needs attention. |
| 3 | **KPI scorecard** | Hover over a cell. Filter to one sector. | Every company against every metric. Each cell says where the figure sits in its own sector (better third, middle third, weaker third, no clear difference, data check) in words and colour. |
| 4 | **Companies** | Pick a company. Read **Evidence quality**. Try the what-if slider. Press **Trace to source and filing**. | Its KPI profile with units, position and distance from the study-sample median; what the numbers say; whether its source, units, validation and human review can be checked; a trend against its sector; the what-if as current and hypothetical position. |
| 5 | **Compare companies** | Pick two or three companies. Then add one from another sector. | A side-by-side matrix with the best company per metric, the comparison in words, a chart, and a warning when the companies are in different sectors. |
| 6 | **Query and chart** | Work down the five steps. Ask for one metric for a sector in one year, then add a second year, then a second metric. Try **Reported figures**. | The question restated in words, a recommended chart with the reason given, what the result shows, and the numbers. |
| 7 | **Compliance check** | Open **What is checked**. Look at the matrix, then the **One company** tab. | What each filing discloses and whether it is internally consistent, with an icon and a word per result. It says plainly that this is a monitoring view, not a legal finding. |
| 8 | **Data quality register** | Filter by status or rule. Open an exception. | Every figure that failed an automatic check as an audit register: figure, issue, status, reviewer, date, with **Open source** and **Verify**. |
| 9 | **Sources and filings** | Pick a company and a KPI. | The chain from the KPI to its inputs, normalisation, validation, filing, SHA-256 fingerprint, retrieval date and human verification. |
| 10 | **Data verification** | Enter a name, mark a value, record it. | The system finding and your decision side by side; your decision is stored with your name and the date and shows on the company page. |
| 11 | **Metrics guide** | The "Explain any value" box already holds a water intensity of 498. Change the number. Open the metrics. | For each metric: what it measures, its unit and formula, how to interpret it, a worked example and its main limitation. |
| 12 | **About** | Read the limitations. | What the system is, what it does and does not do, where the data comes from, and where it stops. |

## Things to try that show the design rules

- On **Compare companies**, put a cement company next to an IT company. The system warns that the figures
  are not like for like and puts large gaps as "619 times as high" instead of an absurd percentage.
- On **Query and chart**, ask for **Reported figures** and notice the warning that raw totals grow with
  company size.
- On **Home**, **Sectors** or **KPI scorecard**, find an amber "Data check". It is impossible (for example
  more waste recovered than generated), so it is shown and flagged but never given a rank.
- On **Compliance check**, look at the year read from a later filing's prior-year column: the system says
  it cannot see an assurance statement there rather than guessing.
- Use the top-bar search to jump to a company, then follow **Trace to source and filing** to its SHA-256.

## Things to know while you judge it

- **It is a pilot.** Twenty companies, about five per sector. A sector median or a rank describes this
  sample, not the sector.
- **A position is not a rating.** Better, middle and weaker third describe where a company sits among the
  others loaded in its sector on one metric. They say nothing about overall environmental performance.
- **A flag or a failed check is not an accusation.** It marks a figure to look at. The cause can be
  rounding, a different reporting boundary, or this system's own unit handling.
- **The compliance check is a disclosure and consistency check.** It does not decide whether a company was
  required to have assurance, because the system does not compute each company's market-capitalisation
  rank.
- **Some years are gaps.** Until the filings for earlier years are loaded, year-on-year change and some
  trends are empty, and the system says so.
- **Your verification is shared.** A decision you record is visible to other visitors and is cleared when
  the app restarts.
- **No usability study has been done.** Claims that these features help users are design arguments.

## Where each EIS concept lives

| EIS concept | Where |
|---|---|
| Status access | Home, top bar: the dataset status and the latest year loaded |
| Critical success factors | KPI scorecard |
| Exception reporting | Home "Needs attention"; Sectors "Needs attention"; Data quality register |
| Drill-down | KPI scorecard, then Companies, then Sources and filings |
| Trend analysis | Sectors "Over time"; Companies; Compare companies |
| Peer comparison | Compare companies |
| Ad hoc query with automatic charts | Query and chart |
| Benchmark comparison and what-if | Companies |
| Compliance monitoring | Compliance check |
| Interpretation | Companies "What do these numbers mean"; Metrics guide; About |
| Traceability and audit | Sources and filings; Data verification |
| Reporting and export | Company briefing; CSV export on every table |
