# Study runbook: what is yours, and what to run once you have data

Everything that can be built without real data is built and tested. This page lists what only you can do
and exactly what to run afterwards. Python is `C:\Users\vitta\.venvs\eis-gauge\Scripts\python.exe`.

## A. Your steps (I cannot do these)

The 2023-24 ASI data are already downloaded and analysed (RESULTS_ASI_2023-24.md). What is left:

1. **Ask your teacher** whether small registered factories (ASI) are acceptable as a stand-in for informal
   units, and whether results from one survey year are enough.
2. **Read the portal's terms of use** (microdata.gov.in, "Policies and Guidelines") and tell me anything
   about limits on thesis or publication use or on sharing. I read none of it; I only downloaded the public file.
3. **Register (free) and download Blocks A, E and H of ASI 2022-23 and 2021-22**, `.dta` format, unedited. They
   let calibration be tested on a year it was not fitted on. Creating the account is yours.
4. Optional: send the Wayback copies of BEE audits or anything from TERI (see DATA_INVENTORY.md).
5. **Decide** the open items in `docs/RESEARCH_DESIGN.md` §9 and `docs/ASI_OPTION.md` §9.

## B. The input the study needs

One CSV, one row per factory and energy item (`docs/cases_example.csv` shows the shape; its rows are
generated, `synthetic = True`):

| column | meaning |
|---|---|
| unit_id | one factory |
| item_id | `grid_electricity`, `coal`, `lignite`, `lpg`, `naphtha`, `kerosene`, `diesel`, `furnace_oil`, `lshs`, `natural_gas` |
| quantity | reference quantity: **kg** for fuels, **kWh** for electricity |
| value_inr | what the factory spent on this item |
| scale | size driver (output value or employees) for the Default proxy |
| sector | group the Default intensity is borrowed from |
| price_group | group the typical price is borrowed from (state and year) |
| cluster | bootstrap cluster (use state and year) |
| synthetic | `False` for real data |

Unmappable item codes are excluded and counted, never guessed. Rows are dropped and counted for missing or
non-positive values and duplicates (the run prints the counts and stores them in the JSON).

## C. Run it

```bash
python -m greeneis.study.run --source csv --path cases.csv --reference "reported to the government (ASI)" --out outputs/study_asi.json
```

Then open the app and the **Study results** page:

```bash
streamlit run dashboard/app.py
```

The page shows the data source, the reference quantity, five verdicts with Holm-adjusted p-values, and the
per-profile table. Results from synthetic data carry a red banner everywhere.

## D. Rules while you do it

- **Do not change a threshold, proxy rule or profile after seeing results.** If a change is genuinely
  needed, record it with the date and the reason in `docs/RESEARCH_DESIGN.md` §10 and rerun everything.
- Report all five hypotheses, including the ones that fail. "Not supported" is a result.
- With fewer than 10 clusters the analysis returns "insufficient data" rather than a verdict.
- The reference quantity is reported, not metered, if it comes from ASI. Say so in the paper.
- The trust scores and ranges tested are the placeholders (V-11). A positive H2 means they should be
  replaced by calibrated values; do that as a separate, documented step, then rerun on a held-out part.

## E. Checks

```bash
python -m pytest        # 130+ tests: engine, validation against CSTEP, trust, hotspots, what-if,
                        # study harness (hand-worked cases), components, pages
python -m ruff check .
```
