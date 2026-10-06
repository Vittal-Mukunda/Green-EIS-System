# REFERENCE FILES

Official public documents downloaded on **2026-10-02** into `data/raw/reference/` (gitignored). This
manifest is tracked so the provenance survives. All five were fetched with a plain HTTP client from
the publisher's own site; each starts with a valid `%PDF` header and its size matched the server's
`Content-Length`.

| File | Source | Bytes | SHA-256 | Used for |
|---|---|---|---|---|
| `amfi_avg_mcap_2025-06-30.pdf` | AMFI, average market capitalisation of listed companies, six months ended 30 June 2025: `https://www.amfiindia.com/Themes/Theme1/downloads/AverageMarketCapitalization30Jun2025.pdf` | 2,175,592 | `bb166eaa42593d6cf1298f47e1cf8efc6312c9cbcc4aaa0fe9565bcafdc81d35` | market-cap ranking for sample selection (V-12); parsed into `data/reference/candidate_pool.csv` |
| `sebi_circular_2023-07-12_brsr_core.pdf` | SEBI circular SEBI/HO/CFD/CFD-SEC-2/P/CIR/2023/122, 12 July 2023: `https://www.sebi.gov.in/sebi_data/attachdocs/jul-2023/1689166456465.pdf` | 226,068 | `f9f437f1d4a92463c00a07223cfc60d4426d79089d070d080f4209f493945afa` | BRSR Core assurance glide path and format applicability (V-14, V-16) |
| `sebi_brsr_format_2023_annexure_II.pdf` | SEBI, Annexure II, updated BRSR format (July 2023): `https://www.sebi.gov.in/sebi_data/commondocs/jul-2023/Annexure_II-Updated-BRSR_p.PDF` | 1,180,453 | `dcc240b2e0b783ce07c4904eebbb2cf2c5bdafeadfe9bb3db900ab56f59ed508` | question wording and numbering for FY2023-24 onward (V-01, V-16, V-20) |
| `sebi_brsr_format_2021_annexure_1.pdf` | SEBI, Annexure I, original BRSR format (May 2021): `https://www.sebi.gov.in/sebi_data/commondocs/may-2021/Business%20responsibility%20and%20sustainability%20reporting%20by%20listed%20entitiesAnnexure1_p.PDF` | 1,258,932 | `056f2e33aed0d29bceead3784d6353c64974b66bf1bb505441084ad5472eb2ee` | question wording and numbering for FY2022-23 filings (V-01, V-16) |
| `sebi_brsr_core_2023_annexure_I.pdf` | SEBI, Annexure I, format of BRSR Core (July 2023): `https://www.sebi.gov.in/sebi_data/commondocs/jul-2023/Annexure_I-Format-of-BRSR-Core_p.pdf` | 747,916 | `af422e91962868a5a953de8f49de6ece6dc2356791abddadcefd59cf75fb50dd` | units, definitions and cross-references (V-02, V-08) |

## Not downloaded (see `docs/DOWNLOAD_CHECKLIST.md`)

- **NSE BRSR XBRL taxonomy** (`Taxonomy_BRSR_20260330194931.zip`, 869 KB): NSE's archive host did not
  answer a plain HTTP request from this machine (timeout), so it needs a browser click.
- **The BRSR filings themselves** (XBRL, and PDFs for the verification sample): NSE's Terms of Use
  prohibit systematic or automated collection, so these are downloaded by hand.

## Derived file

`data/reference/candidate_pool.csv` (tracked): 35 companies from the AMFI table with my own sector
assignment, in three pools (`primary`, `spare`, `not_in_pool`) and notes. The ranking and market caps
come from the AMFI file; **the sector assignment is my judgement from company names, not a data
source**, and the notes marked "(unverified)" are my recollection. Review it before relying on it.
The AMFI table was parsed from the PDF (5,158 rows, every rank 1 to ~5,040 present; the few missing
ranks near 5,042 are ties and do not matter here).
