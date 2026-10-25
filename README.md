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
one-page report, the study harness for the five hypotheses, and an eight-page dashboard. **Not done:** the
study has never run on real data; the trust scores are uncalibrated placeholders; the data source is
undecided (see [docs/DATA_INVENTORY.md](docs/DATA_INVENTORY.md) and [docs/ASI_OPTION.md](docs/ASI_OPTION.md)).
The previous project is archived as the git tag `archive/llm-gauge`.

## Run (Windows, PowerShell)

The virtualenv lives outside OneDrive.

```powershell
& $HOME\.venvs\eis-gauge\Scripts\python.exe -m pytest
& $HOME\.venvs\eis-gauge\Scripts\streamlit.exe run dashboard\app.py
& $HOME\.venvs\eis-gauge\Scripts\python.exe -m greeneis.study.run --source synthetic --out outputs\study_synthetic.json
```

The app opens with an illustrative factory from the reference document (not real data, labelled as such).
The synthetic study run exercises the pipeline only; its results say nothing about the world.
