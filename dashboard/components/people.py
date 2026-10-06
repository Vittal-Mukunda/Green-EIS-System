"""Companies by name: the real name, or the masked code when the sidebar switch asks for codes."""

from __future__ import annotations

import pandas as pd


class People:
    def __init__(self, directory: pd.DataFrame, real: bool) -> None:
        self.real = real
        self.rows = directory.set_index("code").to_dict("index")
        self.codes = list(directory["code"])

    def label(self, code: str) -> str:
        return self.rows[code]["name"] if self.real and code in self.rows else code

    def short(self, code: str) -> str:
        return self.rows[code]["symbol"] if self.real and code in self.rows else code

    def sector(self, code: str) -> str:
        return self.rows[code]["sector"]

    def in_sector(self, sector: str) -> list[str]:
        return [c for c in self.codes if self.rows[c]["sector"] == sector]

    def sectors(self) -> list[str]:
        return sorted({r["sector"] for r in self.rows.values()})

    def rename(
        self, frame: pd.DataFrame, column: str = "code", short: bool = False
    ) -> pd.DataFrame:
        out = frame.copy()
        out[column] = out[column].map(self.short if short else self.label)
        return out
