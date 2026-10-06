# Instructions

You will receive environmental disclosure data for several companies, taken from their annual Business Responsibility and Sustainability Reports (BRSR). Company names are masked: each company is identified only by the code in the heading of its block.

- Use only the evidence given in this message. Do not use any outside knowledge about companies, sectors or the world.
- Assess each company independently of the others.
- All figures are for fiscal year {{ANALYSIS_FY}} unless a column says otherwise. Figures are rounded as printed; use them exactly as printed and do not recompute them.
- Give no text outside the JSON array described under "Output".

## Derived KPIs

Each derived KPI is computed from the reported indicators as follows.

{{KPI_DEFINITIONS}}

## Task 1: t2_class (apply the rule)

Give each company a class, Leader, Average or Laggard, by applying the rule below exactly. The rule uses only the {{ANALYSIS_FY}} values of the three KPIs named in it, as printed in the company's block, and the cut-points of the company's own sector.

{{T2_RULE}}

Cut-points:

{{CUTPOINTS}}

## Task 2: t3_rating, t3_confidence and the rest (your own assessment)

There is no rule for this task. Give your own overall assessment of the company's environmental performance, judged from the evidence given.

- t3_rating: an integer from 1 to 5, where 1 is very weak and 5 is very strong environmental performance.
- t3_confidence: an integer from 1 to 5, where 1 is very low and 5 is very high confidence in your t3_rating.
- top_drivers: exactly {{N_DRIVERS}} different names from the list under "Names for top_drivers", the evidence items that most influenced your t3_rating, most influential first.
- justification: at most {{MAX_WORDS}} words. Every claim in it must name the indicator or KPI it relies on.
- insufficient_evidence: true if the evidence given is not enough for you to give a trustworthy t3_rating, otherwise false.

## Names for top_drivers

Write each name exactly as printed here.

{{DRIVER_NAMES}}

## Output

Return a single JSON array and nothing else: no text before or after it and no code fences. The array contains exactly one object per company in the evidence, in any order. Each object has exactly these keys:

- "company_code": string, the code in the company's block heading
- "t2_class": "Leader", "Average" or "Laggard"
- "t3_rating": integer from 1 to 5
- "t3_confidence": integer from 1 to 5
- "top_drivers": array of exactly {{N_DRIVERS}} different strings, each one of the names listed under "Names for top_drivers"
- "justification": string of at most {{MAX_WORDS}} words
- "insufficient_evidence": true or false
