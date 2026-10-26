"""Where the research-gap pages get their numbers.

Every figure on the Study, analysis and Overall Findings pages comes through this module, so a number is
read from its source file once and shown the same way everywhere. Sources:

- the study result files written by `python -m greeneis.study.run` (ASI 2023-24, main run, declared
  sensitivity runs and the declared textile cut), read through `greeneis.study.headline`;
- the aggregate ASI facts written by `python -m greeneis.study.gap_evidence`;
- the published national estimates (`national.csv`) and the CSTEP recomputation;
- the factor library.

A result file marked synthetic is never returned. A missing file gives ``None``, and the page says so
instead of showing a placeholder.
"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from greeneis.study.headline import Headline, headline

OUTPUTS = Path(__file__).resolve().parents[1] / "outputs"
MAIN_FILE = "study_asi_2023-24.json"
TEXTILE_FILE = "study_asi_2023-24_explor_nic13.json"
SENS_100_FILE = "study_asi_2023-24_sens_100.json"
SENS_NATGAS_FILE = "study_asi_2023-24_sens_natgas.json"
EVIDENCE_FILE = "gap_evidence_asi_2023-24.json"

FUEL_NAMES = {"grid_electricity": "Electricity", "coal": "Coal", "lpg": "LPG"}


@st.cache_data(show_spinner=False)
def _read(path: str, mtime: float) -> dict:
    """The JSON at `path`; `mtime` is only part of the cache key, so an edited file is read again."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def raw(name: str) -> dict | None:
    """A real (not synthetic) result file as a dict, or None if it is missing or synthetic."""
    path = OUTPUTS / name
    if not path.is_file():
        return None
    data = _read(str(path), path.stat().st_mtime)
    prov = data.get("provenance", {})
    return None if prov.get("synthetic", False) else data


def result(name: str) -> Headline | None:
    """The plain-reading summary of a study result file, or None."""
    data = raw(name)
    return None if data is None else headline(data)


def evidence() -> dict | None:
    """The aggregate ASI facts for gaps 1, 3 and 4, or None."""
    return raw(EVIDENCE_FILE)


def source_file(name: str) -> Path | None:
    """The path of a result file that exists, for a download button."""
    path = OUTPUTS / name
    return path if path.is_file() else None


def pct(fraction: float, places: int = 0) -> str:
    return f"{fraction * 100:,.{places}f}%"
