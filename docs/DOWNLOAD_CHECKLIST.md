# Download checklist

Updated 2026-10-05. This is the only list of files still to fetch. Download them yourself in a
browser, a few at a time. NSE's Terms of Use (page dated 29 Oct 2025) prohibit systematic or
automated collection, and NSE's hosts time out from the command line on this machine.

When the 17 XBRL files are in one folder, tell me and I will load them with
`gauge ingest --xbrl <folder> --retrieved-on <the date you downloaded them>`.
The loader names and files the copies. You do not have to rename them first.

If a company shows two rows, take the **latest revision**.

---

## Do this now: 18 items

### 1. One taxonomy archive

Page: <https://www.nseindia.com/companies-listing/xbrl-information>

- [ ] **Taxonomy_Archives** zip (the link at the top of that page)

The three FY2023-24 filings already loaded use `in-capmkt-ent-2024-04-30.xsd`. That schema is not
in the current taxonomy zip (`Taxonomy_BRSR_20260330194931.zip`, already on disk). Download the
archive before the other 17 arrive. Drop the zip anywhere outside `data/raw/` and tell me the path.

Do not use the "XBRL To Excel Converter" on that page (plain HTTP on an Amazon address).
`gauge ingest --inspect-xbrl` does the same job locally.

### 2. Seventeen FY2023-24 XBRL files

Page: <https://www.nseindia.com/companies-listing/corporate-filings-bussiness-sustainabilitiy-reports>
(NSE's spelling).

For each company below:

1. Set **From** `01-04-2024` and **To** `31-03-2025`. The filter is the submission date. FY2023-24
   reports are filed in that window. Leave the default (last twelve months) and you will only see
   FY2025-26 again.
2. Type the company name, pick it from the list, click **GO**.
3. Click the **XBRL** icon on the row whose years read **2023** and **2024**.
4. Save the `.xml` (a filing is a plain XML file, not a zip).

Each of these files carries two years: FY2023-24, and FY2022-23 in the previous-year column.
Together with the FY2025-26 filings already loaded (which carry FY2024-25), that covers the study
window.

| Done | Sector | Company | Type this | NSE symbol | Save as |
|---|---|---|---|---|---|
| | Cement | Ambuja Cements Ltd. | Ambuja Cements | `AMBUJACEM` | `AMBUJACEM_FY2023-24.xml` |
| | Cement | ACC Ltd | ACC | `ACC` | `ACC_FY2023-24.xml` |
| | Iron & Steel | JSW Steel Limited | JSW Steel | `JSWSTEEL` | `JSWSTEEL_FY2023-24.xml` |
| | Iron & Steel | TATA STEEL LIMITED | Tata Steel | `TATASTEEL` | `TATASTEEL_FY2023-24.xml` |
| | Iron & Steel | Jindal Steel & Power Ltd | Jindal Steel | `JINDALSTEL` | `JINDALSTEL_FY2023-24.xml` |
| | Iron & Steel | Jindal Stainless Limited | Jindal Stainless | `JSL` | `JSL_FY2023-24.xml` |
| | Iron & Steel | Steel Authority of India Ltd. | SAIL | `SAIL` | `SAIL_FY2023-24.xml` |
| | IT Services | Tata Consultancy Services Ltd. | TCS | `TCS` | `TCS_FY2023-24.xml` |
| | IT Services | Infosys Ltd | Infosys | `INFY` | `INFY_FY2023-24.xml` |
| | IT Services | HCL Technologies Ltd | HCL Technologies | `HCLTECH` | `HCLTECH_FY2023-24.xml` |
| | IT Services | Wipro Ltd. | Wipro | `WIPRO` | `WIPRO_FY2023-24.xml` |
| | IT Services | Tech Mahindra Limited | Tech Mahindra | `TECHM` | `TECHM_FY2023-24.xml` |
| | FMCG | Hindustan Unilever Ltd. | Hindustan Unilever | `HINDUNILVR` | `HINDUNILVR_FY2023-24.xml` |
| | FMCG | ITC Ltd | ITC | `ITC` | `ITC_FY2023-24.xml` |
| | FMCG | Nestle India Ltd. | Nestle India | `NESTLEIND` | `NESTLEIND_FY2023-24.xml` |
| | FMCG | Britannia Industries Ltd. | Britannia | `BRITANNIA` | `BRITANNIA_FY2023-24.xml` |
| | FMCG | Godrej Consumer Products Ltd. | Godrej Consumer | `GODREJCP` | `GODREJCP_FY2023-24.xml` |

ACC is in the same group as Ambuja. Check that year's reporting boundary when the file is in.
Nestle India may not use an April–March year; if the row is not 2023–2024, stop and tell me
instead of grabbing a different year.

---

## Already on disk (do not download again)

| Item | Status |
|---|---|
| AMFI average market-cap PDF (six months ended 30 June 2025) and four SEBI PDFs | in `data/raw/reference/`. Nothing else from AMFI or SEBI |
| Current BRSR taxonomy zip `Taxonomy_BRSR_20260330194931.zip` | downloaded; holds `in-capmkt-ent-2026-02-28.xsd` |
| FY2025-26 XBRL, all 20 primary companies | `data/raw/xbrl/<SYMBOL>_FY2025-26.xml`. Each also holds FY2024-25 as its previous-year column |
| FY2023-24 XBRL for Shree Cement, UltraTech, JK Cement | loaded 2026-10-05 |
| FY2025-26 PDF for 15 companies | in `data/raw/pdf/`. See the five still missing under "Later" |

The 20 FY2025-26 symbols already loaded: `ULTRACEMCO`, `AMBUJACEM`, `SHREECEM`, `JKCEMENT`, `ACC`,
`JSWSTEEL`, `TATASTEEL`, `JINDALSTEL`, `JSL`, `SAIL`, `TCS`, `INFY`, `HCLTECH`, `WIPRO`, `TECHM`,
`HINDUNILVR`, `ITC`, `NESTLEIND`, `BRITANNIA`, `GODREJCP`.

---

## Later (not this batch)

### Optional: 20 as-filed FY2024-25 XBRL files

Same page. Set **From** `01-04-2025` and **To** `31-03-2026`. Click the XBRL icon on the row whose
years read **2024** and **2025**. One file per primary company (the same 20 symbols as above).

These are optional. FY2024-25 is already loaded from the previous-year column of each FY2025-26
filing (restated by the filer). An as-filed FY2024-25 file would replace that column. UltraTech's
row, seen 2026-10-02, was years `2024 2025`, filed 28-Jul-2025, XBRL 792.98 KB. Do this only if
you want the as-filed year; it is not required to finish the study window (V-23).

### Stage C: PDFs, only after `gauge verify-sample`

That command picks about 10% of the values and names the filing and page. Only then download the
**PDF** (the Attachment column) of the named filings into `data/raw/pdf/`.

Five FY2025-26 PDFs are still missing and will be needed if the sample lands on them:

- [ ] Britannia (`BRITANNIA`)
- [ ] Nestle India (`NESTLEIND`)
- [ ] Godrej Consumer (`GODREJCP`)
- [ ] Infosys (`INFY`)
- [ ] JK Cement (`JKCEMENT`)

The other 15 FY2025-26 PDFs are already filed.

### Spares: do not download unless a primary fails the completeness check

| Sector | Company | NSE symbol | Why it is a spare |
|---|---|---|---|
| Cement | Dalmia Bharat Limited | `DALBHARAT` | next by market cap |
| Cement | The Ramco Cements Limited | `RAMCOCEM` | next by market cap |
| Iron & Steel | APL Apollo Tubes Limited | `APLAPOLLO` | steel tubes, downstream |
| Iron & Steel | Shyam Metalics and Energy Limited | `SHYAMMETL` | next by market cap |
| IT Services | LTIMindtree Limited | `LTIM` | merger in Nov 2022, so FY2022-23 is not like-for-like (unverified) |
| IT Services | Persistent Systems Limited | `PERSISTENT` | next by market cap |
| IT Services | Coforge Limited | `COFORGE` | next by market cap |
| FMCG | Tata Consumer Products Limited | `TATACONSUM` | next by market cap |
| FMCG | Dabur India Ltd. | `DABUR` | next by market cap |
| FMCG | Marico Limited | `MARICO` | next by market cap |

Left out of the pool (do not download): Lloyds Metals (`LLOYDSME`, mining), Hexaware (`HEXT`,
listed Feb 2025), Oracle Financial Services (`OFSS`, products), Varun Beverages (`VBL`), United
Spirits (`UNITDSPR`).

---

## Decisions still open (they do not block this download)

1. **Sample.** Primaries are the AMFI ranking for the six months to 30 June 2025, with sector
   assigned by judgement. ITC is a conglomerate; Nestle India may have changed its year-end. Keep
   both unless you say otherwise.
2. **Revision.** Latest revision of each filing, unless you say otherwise.
3. **Revenue.** The same revenue measure for all three years of a company. The loader records which
   field it used; you do not choose it at download time.
