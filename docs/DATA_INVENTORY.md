# Data inventory (Phase 1a), 2026-10-25

Question: can we obtain unit-level data that supports the study in
[RESEARCH_DESIGN.md](RESEARCH_DESIGN.md) §5? Gate: **≥ 20 units from ≥ 2 clusters**, each with measured
fuel and electricity quantities and at least one proxy variable (cost, hours, production, rated load).

## Verdict

**Gate not met today (0 unit-level audits in hand). Not failed either: two routes are open and both need
you.** Nothing was downloaded; every check below used page text or header-only requests.

| Route | Units | Status | What it needs |
|---|---|---|---|
| A. BEE baseline energy audits (Pali, Indore/Ujjain, Ludhiana) | ≥ 25 named units in 3 clusters, if retrievable | **Files removed from the live BEE site**; archived copies unchecked | An archived copy (see "Your actions") |
| B. SAMEEKSHA cluster profiles and DPRs (137 documents) | cluster aggregates and "typical unit" tables, **not unit audits** | Reachable now | Approval to download (list below); useful for Default-class values and the Tier B fallback only |
| C. MoSPI ASI unit-level microdata (new idea, not yet in the design) | thousands of factories (unverified) | Specified in [ASI_OPTION.md](ASI_OPTION.md) for your review | A free account (yours); terms read by you; documentation download approval |

## A. BEE baseline audits

The web search index still lists these unit-level reports (all on `beeindia.gov.in/sites/default/files/`):

| Cluster | Units named in the index | Prepared by | Notes |
|---|---|---|---|
| Pali textile (Rajasthan) | Vijay Anand, Raj Kumar Textile, Sonu Industries, Shree Rajaram Process / Mills / Prints, Shree Padmawati Dyeing, G G F Industries, Manoj Dyeing, K B Dyeing (10); one report says 11 units audited, March-April 2016 | InsPIRE Network for Environment | plus a "CMP Pali" monitorable-parameters manual (Dec 2017) |
| Indore / Ujjain food (Madhya Pradesh) | Patel Industries, Hira Industries, Nanak Overseas, Rama Agro, JP Hansraj, SR Pulses, Abhishek Industries, Patel Rice Mills, Suresh Chand and Ramesh Chand (9) | DESL | baseline audits, May 2016 |
| Ludhiana forging (Punjab) | Mehram Industries, Khalon International, Akal Enterprises, Tajaka Incorporation, Saggu Toka, Bharat International, NN Products (7); some are **post-implementation**, not baseline | InsPIRE | check which are baseline |
| Manuals | Varanasi brick (Feedback Infra), East-West Godavari refractories (APITCO), BJL Hand Tools (CII), Batala-Jalandhar-Ludhiana foundry (CII, 2011) | various | |

**Availability test (2026-10-25, header-only):** every one of nine sampled unit and manual URLs returns
HTTP 200 with the BEE **homepage** (`text/html`), not a PDF. The same host still serves other PDFs
(`BEE_SME_Website.pdf`, 172,467 bytes), so these files were removed or moved, not blocked.
Archive.org (Wayback Machine) answers **HTTP 429** to this machine, from the shell, the web-fetch tool
and the browser pane, so I could not check for archived copies.

What the index tells us about content: each report follows a template with a baseline field assessment
and a desk-work baseline; consumption tables could not be seen. Whether the figures are metered or
auditor estimates is unknown until a report is read (affects the "measured" label, V-08).

## B. SAMEEKSHA (sameeeksha.org, hosted by TERI)

137 cluster documents listed (cluster profiles, DPRs). The one I read (Pali DPR, 54 pages) gives:
cluster-level annual consumption by fuel (Table 1.1), a "typical unit" at micro/small/medium scale
(48,000 / 360,000 / 2,400,000 kWh per year), and specific energy consumption from observation. That is
the right shape for **Default** values and for generating Tier B units, and the wrong shape for measured
unit data. No terms of use, licence or reuse statement appears on the site (contact: sameeeksha@teri.res.in).
Table 1.1's units look inconsistent (V-10).

## C. ASI unit-level microdata (new option, needs your decision)

The ASI records, per factory, fuels, electricity and water as items with **quantity and purchase value**
(documented for older rounds; recent rounds unverified), plus output and employment. If so, it supports a
variant of the design with large N: reference = **reported quantity**; "Estimated" = value ÷ a typical
price; "Default" = sector median intensity × factory scale, all leave-one-out. Caveats: values are
self-reported to the government, not metered; the ASI covers registered factories, not the informal
sector; access needs a free registration and signed undertakings (confidentiality, no onward sharing,
cite the source); `microdata.gov.in` rejects its certificate from this machine. Under Phase 1 rules
I cannot create the account or accept its terms.

## Downloaded 2026-10-25 (owner-approved)

Saved to `data/reference/` (gitignored). Sizes match the headers; all open as PDFs.

| Saved as | Source | Bytes | SHA-256 (first 16) | What it is |
|---|---|---|---|---|
| `sameeeksha_Pali_Textile_DPR.pdf` | sameeeksha.org `/pdf/dpr/Pali_Textile.pdf` | 2,344,339 | 9fbe5be073a65cbf | BEE **cluster manual**, 168 pp. States "24 energy audit reports provided in Annexure Volumes I to VI" (confirms V-09: the audits are separate volumes, **not in this file**). Detailed audits used instrument measurements (supports calling them measured; V-16 partly) |
| `sameeeksha_Surat_Textile.pdf` | `/pdf/clusterprofile/Surat_textile_cluster.pdf` | 1,943,230 | 8ce86e07270ca7e0 | BEE cluster manual, 104 pp. Studies in the cluster: 15 preliminary, **60 detailed**, 20 technology audits; reports went to the units, not printed here |
| `sameeeksha_Ludhiana_Forging.pdf` | `/pdf/clusterprofile/Ludhiana-Forging-Punjab.pdf` | 1,056,718 | 7f575f2b8f1a7e60 | cluster profile, 16 pp.; typical SEC ranges, no unit data |
| `sameeeksha_Indore_Dal_Mill.pdf` | `/pdf/clusterprofile/Indore-Dal-Mill-Cluster.pdf` | 652,617 | 4c18ada3e981fbe7 | energy profile, 20 pp.; cluster-level SEC, no unit data |
| `sameeeksha_Ludhiana_Brick.pdf` | `/pdf/clusterprofile/ludhiana-brick-cluster.pdf` | 647,038 | 5c9eadc425d325e5 | energy profile, 20 pp.; typical unit about 40,000 bricks/day |
| `bee_SME_Website.pdf` | beeindia.gov.in | 172,467 | 55ccf2e5d6fd6a9f | programme summary: 1,250 SME units audited in 25 clusters; 9,167 units reached by a later project |

**Finding:** none of the six contains unit-level audit data. The unit audits exist (Pali 24, Surat 60
detailed) but sit in annexure volumes or per-unit reports that are not among these files, and the BEE
copies are gone. Route B therefore supplies only typical-unit and cluster values (Default class, Tier B
parameters). It does **not** move the gate. Still unread in detail: the profiles' tables of typical-unit
consumption (to be extracted only if Tier B is chosen).

Unknown: whether the annexure volumes (Pali Vol. I-VI) exist anywhere online. Worth asking TERI
(sameeeksha@teri.res.in) or BEE; I have not contacted anyone.

## Your actions

1. **Archived BEE copies (best route to a Go):** in a browser, after the 429 cools down (try later, or on
   mobile data), open `web.archive.org/web/2022*/beeindia.gov.in/sites/default/files/*` (wildcard), or paste
   one unit URL above into the Wayback Machine. Tell me which units have a snapshot. I will not
   hammer the service.
2. **ASI route (optional):** register at microdata.gov.in, read the access policy, and tell me whether
   the ASI unit-level files list fuel **quantity** per item for the recent years. Then I can specify it.
3. **Any real unit you can reach** (even 5 units with bills and meter readings) would change the plan.
4. Decide: Route C as a second data source, as a replacement, or not at all?

## Decision rule I will apply

- Route A yields ≥ 20 usable units from ≥ 2 clusters → **Go** on the design as written.
- Route A fails, Route C is accessible → redesign around reported-vs-derived (new owner review; H1-H2
  reworded, "measured" no longer claimed).
- Neither → **Tier B** (synthetic from cluster tables), H1-H3 dropped, owner decides whether to proceed.

## Second download round (2026-10-25, after the owner said to download everything possible)

Rule followed: public files only; no account created, no terms accepted, no paywall bypassed.

**The ASI 2023-24 unit-level file is publicly downloadable.** The catalogue page for the round lists
`ASI24m.TXT` (610.2 MB) among its related materials and serves it without a login (HTTP 200). The block-wise
guidelines call the data "freely available for download". Saved **outside the OneDrive project folder** (a
610 MB file would sync) at `C:/Users/vitta/greeneis-data/asi/ASI24m.TXT`, exactly 639,837,328 bytes,
SHA-256 `3622322de1339f0b73b2bf17b1ca4d73f0b61f51bc417a7c47c252284acbd408`. It is gitignored by being outside
the repository. **The portal's terms of use are still unread** (V-18); do not share the file or quote
factory-level rows. Only aggregates should leave this machine until the terms are read.

| Round | Public data file? | How to get the data |
|---|---|---|
| 2023-24 (catalog 256) | **yes**, `ASI24m.TXT` | downloaded |
| 2022-23 (205), 2021-22 (188), 2020-21 (275) | no | free login on microdata.gov.in ("Get Microdata" says "user must be logged in"); account creation is the owner's |

What the file holds (read and counted, `src/greeneis/study/asi.py`): 68,641 factories (57,274 open); 600,530
Block H input-item rows. The three fixed fuel lines carry a quantity: electricity purchased (57,918 factories,
all in kWh), coal (4,133, all in tonnes), gas (5,572, all in kg). The petrol/diesel/oil, other-fuel and
own-generated-electricity lines carry **no quantity** in any row (0 of 47,621 / 7,701 / 5,330). Specific fuel
products listed among a factory's ordinary input items are rare (diesel 50, furnace oil 77, LPG 142, pet coke
71 rows). Reported rate always equals value divided by quantity (it is derived, not independent).

**Documents** (in `data/reference/`, gitignored): `asi_docs/` holds the data structure, schedule, code list,
concepts, instruction manual, NPCMS product classification and unit-level-data note for 2023-24, and the
same layout documents for 2021-22. `papers/` holds the open-access papers below.

| File | Bytes | SHA-256 (first 16) |
|---|---|---|
| papers/CEA_CO2_baseline_user_guide_v20.pdf | 1,171,206 | b881c258f58fd77c |
| papers/CEEW_2018_informal_manufacturing_brief.pdf | 1,166,501 | a02cff5474b81d37 |
| papers/CSTEP_2018_GHG_informal_sector.pdf | 1,246,175 | 03ee49af4507ba9f |
| papers/GHGPI_2017_industry_subsector_estimates.pdf | 1,405,248 | 4a7b75db682500e4 |
| papers/GHG_Protocol_quantitative_uncertainty.pdf | 163,501 | 1d644ddc95c00ef4 |
| papers/NIST_IR_7850_2012.pdf | 1,560,347 | 844f80d8f227d670 |
| papers/UTS_AI_assisted_emission_reporting_SMEs.pdf | 183,353 | cc0af7df9e606af3 |

**Not obtainable (and not circumvented):** Halat et al. 2026 (publisher returns 403), the ADB 2024 report
(403), Kuo et al. 2015 (503 at the time; retry later).

**BEE archived reports via the Wayback Machine.** The archive's CDX index lists copies of 7 BEE sector
energy-mapping reports (brick, chemical, forging, foundry, glass and refractory, paper, pharma; 2.4-6.7 MB each),
the Akal Enterprises unit audit (Ludhiana forging), BJL Hand Tools, the Varanasi brick and Godavari
refractory manuals, the Howrah galvanizing manual, a brick-sector blueprint and a Jorhat situation analysis.
**None downloaded yet:** the archive's file endpoint answered "429 Too Many Requests" to every attempt (my
index queries probably used the allowance); a slow retry with back-off (up to 3 minutes between tries, 30 s between files) was also refused for the first
two files, so I stopped it rather than prolong the block. Retry from another network later, or open the
copies by hand in a browser on web.archive.org. The Pali and Indore
unit audits (Vijay Anand, Raj Kumar, Nanak Overseas and others) are **not in the index** under those names.
