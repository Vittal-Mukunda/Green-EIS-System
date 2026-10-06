"""Load and store the informational SDG mapping. Shown in the dashboard only, never to a model."""

from __future__ import annotations

from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete
from sqlalchemy.orm import Session

from gauge import vocab
from gauge.config import ConfigError, IndicatorsConfig, StudyConfig
from gauge.db.models import SdgMapping

SDG_SOURCE = "https://sdgs.un.org/goals (target wording); pairing is the project author's reading"


class SdgEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    sdg: int = Field(ge=1, le=17)
    target: str | None
    note: str

    @model_validator(mode="after")
    def _target_matches_goal(self) -> Self:
        if self.target is not None and not self.target.startswith(f"{self.sdg}."):
            raise ValueError(
                f"{self.code}: target {self.target!r} does not belong to SDG {self.sdg}"
            )
        return self


class SdgConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    caption: str
    mappings: list[SdgEntry]

    @model_validator(mode="after")
    def _caption_is_the_required_one(self) -> Self:
        if self.caption != vocab.SDG_CAPTION:
            raise ValueError(f"caption must be exactly {vocab.SDG_CAPTION!r}")
        return self


def load_sdg_mapping(cfg: StudyConfig, indicators: IndicatorsConfig) -> SdgConfig:
    path = cfg.path("config/sdg_mapping.yaml")
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        sdg = SdgConfig(**yaml.safe_load(path.read_text(encoding="utf-8")))
    except ValueError as exc:
        raise ConfigError(f"invalid SDG mapping {path}: {exc}") from exc
    known = {i.code for i in indicators.indicators} | {k.code for k in indicators.kpis}
    unknown = sorted({m.code for m in sdg.mappings} - known)
    if unknown:
        raise ConfigError(f"SDG mapping references unknown indicator/KPI codes: {unknown}")
    pairs = [(m.code, m.sdg) for m in sdg.mappings]
    if len(set(pairs)) != len(pairs):
        raise ConfigError("SDG mapping has duplicate (code, sdg) pairs")
    return sdg


def sync_sdg_mapping(session: Session, sdg: SdgConfig) -> int:
    """Replace the sdg_mapping table with the configured mapping (static reference data)."""
    session.execute(delete(SdgMapping))
    session.add_all(
        SdgMapping(indicator_code=m.code, sdg_number=m.sdg, sdg_target=m.target, source=SDG_SOURCE)
        for m in sdg.mappings
    )
    session.flush()
    return len(sdg.mappings)
