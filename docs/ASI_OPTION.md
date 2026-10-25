# Option C: ASI factory microdata (DRAFT for owner review, 2026-10-25)

Status: **proposal, not adopted.** It changes the study's reference data and the wording of H1-H5, so it
needs your decision (see §9). Facts marked *unverified* have not been checked against the ASI files; checking
them is the first step (§7).

> **Update 2026-10-25 (later):** the 2023-24 unit-level file turned out to be publicly downloadable. It was
> downloaded, parsed and the pre-specified study was run on it; see `docs/RESULTS_ASI_2023-24.md`. The
> findings below about the schedule were confirmed on the real file (counts in DATA_INVENTORY.md). Earlier
> rounds still need the free login.

## 0. What the 2022-23 documentation actually shows (read 2026-10-25)

I downloaded and read four public documents of the 2022-23 round (catalog 205: data structure, schedule,
code list, block guidelines). This replaces several assumptions below.

**Good news**
- The unit-level data are described as "freely available for download on the Ministry's website"
  (block-wise guidelines). 68,462 factories in Block A; 592,670 input-item rows in Block H.
- **Block H** (indigenous input items) has, per factory and item: NPCMS item code, unit code, **quantity
  consumed**, **purchase value (Rs)** and **rate per unit (Rs)**. That is the pair the study needs.
- The fuel lines are fixed codes with fixed units, so the item mapping is trivial:

| Schedule line | NPCMS code | Unit | Library item |
|---|---|---|---|
| Electricity purchased and consumed | 9990500 | kWh | `grid_electricity` |
| Coal consumed | 9990700 | tonne | `coal` (grade unknown, flagged) |
| Gas consumed | 9990900 | kg | **ambiguous**: LPG or natural gas (V-29) |

- Scale and grouping variables exist: Block A has state (A7), 4-digit industry (A4), total cost of
  production (COSTOP) and a survey multiplier (MULT); Block E has average persons worked (E_I6).
- Only **Blocks A, E and H** are needed.

**Bad news (changes what H4 and H5 can say)**
- **Liquid fuels are lumped.** "Petrol, diesel, oil, lubricants" (9990600) and "Other fuel" (9920400)
  have **no unit** in the schedule, so a quantity cannot be converted to emissions. Diesel and furnace oil,
  important for small units in CSTEP's data, are therefore **not usable** from ASI.
- So each factory has at most **three** usable items (electricity, coal, gas). The hotspot tests (H4, H5)
  would compare at most three activities, and only factories using coal or gas have two or more.
- The ASI covers registered factories (the smallest are about 10 workers with power), not informal units.
- Data files come as `.txt` (conversion tool needs a Visual FoxPro runtime) or `.dta`, `.sav`, `.dbf`
  (pandas reads `.dta`; pick that format).
- Whether the portal download needs a login or signed undertakings is still unread (V-18).

**What still has to be checked on a real file:** how many factories report coal or gas with both quantity
and value; whether the rate per unit is the factory's own entry; the unit codes (HI4) for the three lines.

## 1. Why consider it

Route A (BEE unit audits) is not retrievable today (DATA_INVENTORY.md). The Annual Survey of Industries
(ASI, MoSPI) is a factory-level dataset, free to registered users, with catalog entries on
`microdata.gov.in` for 2011-12 through 2023-24, each with a unit-level data note, record layout and code
list. The 2021-22, 2022-23 and 2020-21 entries carry a "fuels consumed" block (*unverified for item-level
quantity in these rounds*; older rounds have quantity **and** purchase value per fuel, electricity and
water item).

If per-item quantity and value are present, they give the one thing the study needs and nothing else here
does: **many factories where both the reported quantity and the spend are known**, so the error of a
spend-based estimate and of a sector default can be measured directly, at a sample size no audit set offers.

## 2. What it changes in the design (honestly)

| Aspect | RESEARCH_DESIGN as written | With ASI |
|---|---|---|
| Reference ("truth") | audit-**measured** quantity | **reported** quantity (self-reported to the government, probably from purchase records; not metered) |
| Class "Measured" | the reference | renamed **Reported** and used as the reference only |
| Class "Estimated" | proxy from audit fields (spend ÷ price, hours × rating) | **spend ÷ typical price** only (price = leave-one-out median unit value of the same item, same state and year) |
| Class "Default" | cluster-typical value × size | **sector median intensity × factory scale** (leave-one-out; scale = output value or employees) |
| Units | small units in named clusters | **registered factories**, restricted to small ones (average persons worked ≤ *placeholder* 50) in selected sectors; **only electricity, coal and gas** (see §0) |
| N | tens of units | thousands (*to be verified*) |
| "Informal" framing | direct | **weakened**: ASI excludes the informal sector; say "small registered factories as a stand-in" |

H1-H5 survive with reworded references ("error against the reported quantity"). H2 and H3 become stronger
(real calibration, large N); hours × rated-load proxies and cluster context are lost.

## 3. Prior use (do not overclaim)

CEEW (2017) already used ASI unit-level data to estimate industrial emissions by fuel (IPCC-style
activity × factor); so "emissions from ASI" is not new here. What is new is the **error calibration of
data-class labels** for small units, not the emission arithmetic.

## 4. Data needed (all *unverified until the documentation is read*)

- Per factory: anonymised id, state, NIC code, employees, output value, fixed capital (if offered).
- Fuel, electricity and water block: item code, quantity, unit, purchase value; electricity purchased
  (kWh, value) and own generation.
- Code list mapping item codes to fuels; schedule and instruction manual (to see how quantity is defined).
- Rounds: 2022-23 (catalog 205) is documented; 2021-22 (188) and 2023-24 (256) can add years if the layout matches (unchecked).
- Needed blocks only: A (state, industry, cost of production, multiplier), E (persons), H (input items).

## 5. Derivations and outcomes (same machinery as the main design)

For each factory × fuel item with both quantity q and value v:
- **Estimated:** q̂_E = v ÷ p̃, with p̃ the median of q/v over *other* factories in the same state-year-item.
- **Default:** q̂_D = (median over *other* same-sector factories of q ÷ scale) × this factory's scale.
- **Error:** ε = (q̂ − q) ÷ q, per class, per item.
Then emissions by fuel via the factor library, totals, hotspot ranking across the factory's fuel items,
trust index under profiles, and H1-H5 as in RESEARCH_DESIGN §4. Dependence: factories share prices within
a state-year, so cluster the bootstrap by **state × year**, not only by factory. With large N, report effect
sizes and intervals, not p-values alone.

## 6. New risks specific to ASI

- **Item-to-fuel mapping is a judgement** (e.g. "coal" without grade, "other fuels", "firewood/biomass"):
  each mapping becomes a logged, verifiable decision; unmappable items are excluded and counted.
- **Reported ≠ true:** rounding, reporting in wrong units, copy-forward values. Outlier rules fixed *before*
  seeing errors (log them), or the errors we calibrate are mostly typos.
- **Value-only records:** factories that report value without quantity cannot be scored; report how many.
- **Price proxy confounded** with fuel quality and region; the H1 comparison tests proxies, not owners.
- **Access terms:** registration, undertakings (confidentiality, no onward sharing, cite the source). The
  data cannot be committed to the repository or shared with the teacher as files; only aggregates.
- **File size:** the 2023-24 unit-level text file is about 610 MB (as listed in the catalog).

## 7. Feasibility gate for this option (before any big download)

1. **You** register on `microdata.gov.in` and read the access policy (I cannot create the account or
   accept terms). Tell me anything unusual in it (fees, approval delay, restrictions on thesis or
   publication use).
2. **Done 2026-10-25** (§0): quantity and value exist, but only for electricity, coal and gas.
3. **Go** if the documentation shows quantity and value per fuel item, and a count of small factories with
   ≥ 1 fuel item with both fields exceeds *placeholder* 2,000 in ≥ 2 sectors (taken from published
   tabulations or a first small extract). Otherwise this option is dropped.
4. Only then do I ask to download a unit-level file (name, size) for approval.

## 8. Recommended use: a hybrid, not a replacement

| Part | Source | Used for |
|---|---|---|
| Error calibration of Estimated and Default classes | ASI (this option) | H1, H2, H3 |
| Hotspot and prioritisation tests | ASI multi-fuel factories | H4, H5 |
| Worked cases and the demonstration | BEE audits if recovered, otherwise SAMEEKSHA typical-unit tables | the dashboard, the narrative |
| Engine validation | CSTEP / CEEW published tables | ref §6 checks |

This keeps the project's stated gap (informal sector, firm-level data) as the motivation and the demo
setting, and is explicit that the calibration comes from small registered factories.

## 9. Decisions for you

1. Adopt Option C as the calibration data source (hybrid above), replace the design with it, or drop it?
2. Is "small registered factories as a stand-in for informal units" acceptable to your teacher? If the
   teacher insists on informal units only, Option C is not suitable and the fallback is Tier B.
3. Employee cut-off for "small" (placeholder 50) and sectors (proposal: textiles NIC 13, non-metallic
   minerals incl. bricks NIC 23, basic metals NIC 24, food NIC 10: the main coal users in CEEW/CSTEP).
4. Will you register, and read the terms first?
