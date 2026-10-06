"""Typed loading of config/xbrl_mapping.yaml and config/xbrl_overrides.yaml."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from gauge import vocab
from gauge.config import ConfigError, IndicatorsConfig, StudyConfig
from gauge.standardize.units import UnitError, factor_to_canonical

MAPPING_FILE = "config/xbrl_mapping.yaml"
OVERRIDES_FILE = "config/xbrl_overrides.yaml"
CIN_FILE = "data/reference/cin_isin.csv"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IndicatorMap(_Strict):
    element: str
    kind: Literal["currency", "energy", "emissions", "volume", "mass"]


class Identity(_Strict):
    isin: str
    cin: str  # present in filings that do not carry an ISIN fact
    name: str
    boundary: str
    assurer_name: str


class Ambiguity(_Strict):
    emissions_label_tonnes_min: int = Field(gt=0)
    emissions_tonnes_unit: str
    revenue_min_inr: int = Field(gt=0)
    revenue_max_inr: int = Field(gt=0)
    revenue_unit: str
    yoy_scale_break_ratio: float = Field(gt=1)


class IntensityCheck(_Strict):
    intensity: str
    absolute: list[str]


class XbrlMapping(_Strict):
    schema_refs: list[str] = Field(min_length=1)
    identity: Identity
    boundary_values: dict[str, str]
    indicators: dict[str, IndicatorMap]
    unit_labels: dict[str, str | None]
    ambiguity: Ambiguity
    revenue_anchors: list[str]
    assurance_groups: dict[str, str]
    assurance_accepted: list[str]
    intensity_checks: dict[str, IntensityCheck]
    intensity_tolerance: float = Field(gt=0, lt=1)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if not set(self.boundary_values.values()) <= set(vocab.BOUNDARIES):
            raise ValueError(f"boundary_values must map to {list(vocab.BOUNDARIES)}")
        for check in self.intensity_checks.values():
            unknown = set(check.absolute) - set(self.indicators)
            if unknown:
                raise ValueError(
                    f"intensity check references unmapped indicators {sorted(unknown)}"
                )
        return self


class Override(_Strict):
    isin: str
    fy: list[str] = Field(min_length=1)
    indicators: list[str] = Field(min_length=1)
    unit: str
    evidence: str = Field(min_length=20)  # an override without evidence is not allowed

    @model_validator(mode="after")
    def _fy_format(self) -> Self:
        if not all(vocab.FY_RE.match(fy) for fy in self.fy):
            raise ValueError(f"override fy must look like FY2024-25: {self.fy}")
        return self


class OverridesFile(_Strict):
    overrides: list[Override] = []


def _read(path: Path) -> dict:
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a YAML mapping")
    return data


def load_xbrl_mapping(cfg: StudyConfig, indicators: IndicatorsConfig) -> XbrlMapping:
    path = cfg.path(MAPPING_FILE)
    try:
        mapping = XbrlMapping(**_read(path))
    except ValueError as exc:
        raise ConfigError(f"invalid XBRL mapping {path}: {exc}") from exc
    codes = {i.code: i for i in indicators.indicators}
    if set(mapping.indicators) != set(codes):
        missing = sorted(set(codes) - set(mapping.indicators))
        extra = sorted(set(mapping.indicators) - set(codes))
        raise ConfigError(
            f"XBRL mapping must cover every indicator; missing {missing}, unknown {extra}"
        )
    return mapping


def load_cin_map(root: Path) -> dict[str, str]:
    """CIN -> ISIN, from filings that state both. Missing file means no older-taxonomy filings can load."""
    path = root / CIN_FILE
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None or not {"cin", "isin"} <= set(reader.fieldnames):
            raise ConfigError(f"{path} must have cin and isin columns")
        for row in reader:
            cin, isin = (row.get("cin") or "").strip(), (row.get("isin") or "").strip()
            if not cin or not isin:
                raise ConfigError(f"{path}: a row is missing cin or isin")
            if cin in out and out[cin] != isin:
                raise ConfigError(f"{path}: {cin} maps to both {out[cin]} and {isin}")
            out[cin] = isin
    return out


def load_overrides(cfg: StudyConfig, indicators: IndicatorsConfig) -> list[Override]:
    path = cfg.path(OVERRIDES_FILE)
    if not path.is_file():
        return []
    try:
        overrides = OverridesFile(**_read(path)).overrides
    except ValueError as exc:
        raise ConfigError(f"invalid XBRL overrides {path}: {exc}") from exc
    canonical = {i.code: i.unit for i in indicators.indicators}
    for o in overrides:
        for code in o.indicators:
            if code not in canonical:
                raise ConfigError(f"override for {o.isin}: unknown indicator {code!r}")
            try:
                factor_to_canonical(o.unit, canonical[code])
            except UnitError as exc:
                raise ConfigError(f"override for {o.isin} {code}: {exc}") from exc
    return overrides
