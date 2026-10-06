# Why this is an EIS, why it is built this way, and who it helps

This document supports an oral or written defence. It separates three kinds of statement: **built and
tested** (you can show it), **design argument** (a reasoned case, not a measurement), and **not done**.
"Most optimal" cannot be proven for a system like this, so the claim made here is narrower and defensible:
for this problem, with these constraints, the design below meets the requirements better than the
alternatives considered, and the reasons are stated so they can be challenged.

## 1. What an EIS is, and the capability list used

An executive information system gives decision-makers fast, summarised, visual access to the
information they need, with the ability to see exceptions and to drill down to the detail behind a
figure. The capabilities usually listed are: **drill-down, exception reporting, trend analysis, status
access, critical success factors, graphical display, integration of several data sources, and ease of
use**. The list used here is taken from the summary at
[Wikipedia: Executive information system](https://en.wikipedia.org/wiki/Executive_information_system).

The foundational sources are Rockart and Treacy, "The CEO goes on-line", *Harvard Business Review*
60(1), 1982, pp. 32-38, and Watson, Rainer and Koh, "Executive information systems: a framework for
development and a survey of current practices", *MIS Quarterly* 15(1), 1991, pp. 13-30. Their existence and
bibliographic details were confirmed; **their text was not read for this document**, so do not attribute a
specific feature to either paper until you have read it (VERIFY V-41).

The system adds three things the classic list does not stress, because the data here is regulatory
disclosure rather than internal accounts: **decision support** (what-if), **trust in the numbers**
(provenance, validation, human checking) and **interpretation aids** (plain-language reading, definitions,
stated limits).

## 2. Capability audit

Every row is built, in the running system, and covered by an automated test unless it says otherwise.
The system has twelve evidence pages, each opening with what it shows, what is being compared and how to
read it, and each carrying units on every number.

| Capability | Where | What it does |
|---|---|---|
| Status access | Home, Sectors | The current picture, stamped with the latest fiscal year loaded and the date the filings were retrieved |
| Critical success factors | KPI scorecard | Five metrics for every company, coloured by position within its own sector |
| Exception reporting | Sectors ("Needs attention"), Data quality register | What to look at first in a sector, and the full register of figures that failed a check |
| Drill-down | KPI scorecard, Companies, Sources and filings | Scorecard, then company, then figure, then the filing it was read from. "Open a company" buttons jump straight to a profile |
| Trend analysis | Sectors, Companies, Compare companies | Year-on-year movement, and lines over time for a company, a sector or chosen companies |
| Peer comparison | Compare companies | Chosen companies side by side, with who is best and by how much stated in words, and a warning across sectors |
| Ad hoc query with automatic charts | Query and chart | The user chooses the data type, metrics, companies and years; the chart type is picked from the shape of the question, with the reason shown |
| Benchmark comparison | Companies | Distance of each metric from the sector median, as a percentage change |
| Decision support | Companies | A what-if: the company's rank if one metric moved by a chosen percentage |
| Compliance monitoring | Compliance check | Does each filing disclose the BRSR Core figures, state its boundary and assurance, and stay internally consistent? |
| Data integration | Sources and filings | XBRL and PDF sources reconciled to one schema, one row per filing |
| Traceability and audit | Sources and filings, Data verification | Every value traced to a file, a SHA-256 fingerprint and the person who checked it |
| Data-quality assurance | Data quality register, Data verification | Rules find defects; a person confirms or corrects them |
| Interpretation aids | Companies, Metrics guide, About | A plain-language reading per company, what each number means with a worked example, a glossary, the limits of the data |
| Reporting and export | Companies, Query and chart, Compare companies | A one-page Markdown briefing per company and CSV export of every table |
| Soft information | Companies, Data verification | Reviewers' notes are stored with, and shown beside, the figures they concern |
| Ease of use | all pages | No login, real company names, a one-line description under each page name, a page address for each page, and a Home page that leads to each kind of question. Whether it is easy enough has not been tested (section 6) |

### Deliberately not built, and why

| Capability | Reason |
|---|---|
| Real-time status and push alerts | The source data is an annual disclosure. There is no feed to be real-time about, so "status access" means the latest filing, with its date shown |
| Forecasting | Two or three yearly points per company cannot support a forecast, and offering one would imply precision the data lacks. The what-if is arithmetic, labelled as such |
| User accounts, roles, personalised views | The brief for the demonstration is that anyone can open it with no sign-in |
| Free-form query language (SQL or similar) | Replaced by the guided Query and chart page. Executives need guided questions, and an open query box invites unreproducible answers |
| A decision on whether assurance was legally required of a company | It depends on each company's market-capitalisation rank, which the system does not compute. The Compliance check reports what the filing states and says so |
| External targets and peer data | None have been verified, so benchmarks are the sample's own peers and are labelled that way |

## 3. Why this design

The requirements that drove the design, in order of weight:

1. **Every number must be defensible.** A figure that cannot be traced to a filing is worth little to an
   analyst, an auditor or an examiner.
2. **Defects in the source must be found, not passed on.** Self-reported disclosures contain
   impossibilities.
3. **A reader must be able to interpret the number without being an expert.**
4. **The result must be reproducible and cheap.** No paid services, rerunnable end to end.

Against those, the alternatives considered:

| Alternative | Strength | Why it falls short here |
|---|---|---|
| A spreadsheet | Familiar and flexible | No enforced lineage, no validation rules, no audit trail. A bad cell is silent, and a rank built on it looks authoritative |
| A commercial BI tool over the same data | Better charting, and views are quicker to build | It would still need the ingestion, unit-reconciliation and validation pipeline, which is where the correctness lives; the presentation layer is the cheaper part to replace. Pointing a BI tool at this system's database is a reasonable next step |
| A commercial ESG data vendor | Wide coverage | Methodology is generally proprietary, so a figure cannot be traced to the filing (general knowledge; not checked for specific vendors) |
| Asking a language model about the filings | Fast | Not reproducible and not traceable. This project's own research is about exactly that unreliability, which is why the numbers here come from a deterministic pipeline and the models are measured against it, not used as the source |

The argument in one sentence: the decision-relevant value is not the chart, it is the **chain of
assurance** from filing to figure, and that chain (standardise, validate, compute exactly, trace, let a
person check) is what this design spends its effort on.

## 4. What the interpretation features are for, and the rules behind them

These exist because a number alone does not tell a reader what to conclude. Each is deterministic
arithmetic or fixed templates: there is no model anywhere in the evidence views.

- **Position within sector (better, middle, weaker third).** A raw intensity means nothing across
  sectors, so each company is placed only among the others in its own sector.
- **"No clear difference".** If a sector's values lie within 1% of their median, ranking them would
  manufacture a difference. In the real data for FY2025-26, Cement's waste-recovery rates (excluding the impossible
  figure below) run from 99.84% to 99.9998%, and a rank there would be noise.
- **"Data check" instead of a rank.** In the real data, CEM-03 reports recovering 103.5% of the waste it
  generated, which is impossible. Without this rule it would be ranked first in its sector on that KPI.
  It is shown, not ranked, and left out of the sector median. The same rule stops a movement being
  measured against a prior-year value that failed a check.
- **"About the same".** A year-on-year change under 1% is not called better or worse.
- **Plain-language reading.** Each company's year in sentences, generated from the figures, with the
  evidence behind them (flags, values checked, assurance, boundary) in the last line.
- **What-if.** Arithmetic on today's figures with everyone else held fixed. It shows how sensitive a
  rank is, which is often the real question, and says it is not a forecast.

The thresholds (thirds by rank, 1%, 1%, a 10% default for attention) are **design choices, not derived
from the data**. They are named constants, listed in VERIFY V-42, and the attention threshold is a slider.

## 5. Who it helps, and how

| User | What they get |
|---|---|
| Sustainability or ESG analyst | Comparable intensities across companies in a sector, with the defects in each filing surfaced instead of discovered later |
| Investment or credit analyst | A fast within-sector screen, and a briefing per company that states its own evidence quality |
| Assurance provider or auditor | The filing, its fingerprint and every figure's source in one place, and a place to record what was checked |
| Company management | Where the company sits against peers, how far it is from the median, and what a change would do to its rank |
| Researcher or examiner | A reproducible pipeline whose every output is traceable, and honest statements of its limits |

What the real data already shows when the system is used this way: **three of the twenty companies
report recovering more waste than they generated in the latest year, and the system refuses to rank them
rather than rewarding the impossibility**; nine unit corrections (across companies and years) were needed, each justified by the
filing PDF; and the largest year-on-year movements are listed first with their sizes, so the first thing a reader
sees is what moved, not a wall of figures. These are findings about the filings, not judgements about the
companies.

## 6. What has not been shown

- **No usability evaluation has been done.** The claim that the interpretation features help users is a
  design argument. A modest test would be enough to evidence it: give five people the same five tasks
  (find a sector's weakest company on a KPI, explain why a company is not ranked, find a figure's source,
  say what would change a company's position, find what needs attention), once with the dashboard and once
  with the raw table, and record time and errors. A short standard questionnaire such as the System
  Usability Scale could accompany it.
- **Pilot scale.** Twenty companies in four sectors. Medians and ranks describe the sample.
- **Positions are not ratings** and are never described as environmental performance.
- **Self-reported data.** A flag marks a figure to check, not a finding of misreporting.
- **The Iron & Steel sample may mix producers whose figures are not like for like** (VERIFY V-40).

## 7. Where each claim can be demonstrated

`docs/DEMO_WALKTHROUGH.md` is the tour. The About page in the running system lists the capabilities
above with the page each lives in, and a test checks that every page named there exists.
