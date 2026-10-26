# GreenEIS

Green Enterprise Information System for sustainability analytics: a lightweight tool that turns a small
Indian manufacturing unit's monthly energy, fuel and cost data into emissions, a trust score for each
number, hotspots, a cost link and what-if scenarios. Course project (Industrial Engineering and
Management, Enterprise Information Systems), intended to become a short paper.

The research question is whether the trust score (Measured / Estimated / Default) actually predicts the
error in a unit's footprint and the stability of its hotspot ranking. That is tested on real data once the
owner has it; see [docs/RESEARCH_DESIGN.md](docs/RESEARCH_DESIGN.md) and
[docs/STUDY_RUNBOOK.md](docs/STUDY_RUNBOOK.md).

Evidence base and proposed design:
[docs/reference/GreenEIS_Research_and_Design_Reference.docx](docs/reference/GreenEIS_Research_and_Design_Reference.docx).
Working notes, decisions and rules for Claude Code: [CLAUDE.md](CLAUDE.md).

## State

Built and tested: factor library, emission engine (checked against the reference document's worked example
and CSTEP's published tables), trust score, hotspots and cost link, what-if scenarios, recommendations,
one-page report, the study harness for the five hypotheses, and an eight-page dashboard. The study has been
run once on real data (ASI 2023-24 factory returns): see [docs/RESULTS_ASI_2023-24.md](docs/RESULTS_ASI_2023-24.md)
for what it does and does not show. **Not done:** the trust scores are still uncalibrated placeholders; the
ASI terms of use are unread; calibration is untested on a second year (see
[docs/DATA_INVENTORY.md](docs/DATA_INVENTORY.md)).
The previous project is archived as the git tag `archive/llm-gauge`.

## Where to read

| Document | What it is |
|---|---|
| [docs/FINDINGS.md](docs/FINDINGS.md) | everything established so far, one page |
| [docs/DATA_TO_COLLECT.md](docs/DATA_TO_COLLECT.md) | the data still needed, and the sector chosen (textile wet processing) |
| [docs/RESEARCH_DESIGN.md](docs/RESEARCH_DESIGN.md) | question, hypotheses H1-H5, threats, change log |
| [docs/RESULTS_ASI_2023-24.md](docs/RESULTS_ASI_2023-24.md) | first real-data results and their caveats |
| [docs/DATA_INVENTORY.md](docs/DATA_INVENTORY.md), [docs/ASI_OPTION.md](docs/ASI_OPTION.md) | what data exist and how ASI is used |
| [docs/STUDY_RUNBOOK.md](docs/STUDY_RUNBOOK.md), [docs/VERIFY.md](docs/VERIFY.md) | owner's steps; unverified-items register |
| [docs/UI_DESIGN.md](docs/UI_DESIGN.md), [docs/PHASE1_SPEC.md](docs/PHASE1_SPEC.md) | interface and engine specification |

## Host it (Streamlit Community Cloud)

Sign in at share.streamlit.io with GitHub, choose **Create app**, repository
`Vittal-Mukunda/Green-EIS-System`, branch `main`, main file `dashboard/app.py`, Python 3.12. The app needs
only `requirements.txt`. The Study results page shows the aggregate ASI 2023-24 results in `outputs/`
(factory-level rows are never committed).

## Run (Windows, PowerShell)

The virtualenv lives outside OneDrive.

```powershell
& $HOME\.venvs\eis-gauge\Scripts\python.exe -m pytest
& $HOME\.venvs\eis-gauge\Scripts\streamlit.exe run dashboard\app.py
& $HOME\.venvs\eis-gauge\Scripts\python.exe -m greeneis.study.run --source synthetic --out outputs\study_synthetic.json
```

The app opens with an illustrative factory from the reference document (not real data, labelled as such).
The synthetic study run exercises the pipeline only; its results say nothing about the world.
