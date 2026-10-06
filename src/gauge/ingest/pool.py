"""The candidate pool (data/reference/candidate_pool.csv): the sample frame, keyed by ISIN.

The pool names every company the study may use, with its sector and whether it is a primary pick
or a spare. Filings are matched to companies by the ISIN they declare, so an unknown ISIN is an
error, not a silent new company. The sector assignment is the project author's judgement (V-22).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

POOL_FILE = "data/reference/candidate_pool.csv"


@dataclass(frozen=True)
class PoolEntry:
    isin: str
    sector: str
    pool: str  # primary | spare | not_in_pool
    nse_symbol: str
    company_name: str
    amfi_rank: int
    note: str


def load_pool(root: Path, relative: str = POOL_FILE) -> dict[str, PoolEntry]:
    path = root / relative
    if not path.is_file():
        raise FileNotFoundError(f"candidate pool not found: {path}")
    out: dict[str, PoolEntry] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            entry = PoolEntry(
                isin=row["isin"], sector=row["sector"], pool=row["pool"],
                nse_symbol=row["nse_symbol"], company_name=row["company_name"],
                amfi_rank=int(row["amfi_rank"]), note=row["note"],
            )  # fmt: skip
            if entry.isin in out:
                raise ValueError(f"duplicate ISIN in candidate pool: {entry.isin}")
            out[entry.isin] = entry
    return out
