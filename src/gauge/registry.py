"""Idempotent sync of config-derived reference rows (sectors, conditions, models, SDG map)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from gauge.config import ModelsConfig, StudyConfig, load_indicators
from gauge.db.models import Condition, Model, Sector
from gauge.sdg.mapping import load_sdg_mapping, sync_sdg_mapping

CONDITION_TEXT = {
    "C1": "Baseline: raw indicators + derived KPIs, FY2024-25 only.",
    "C2": "Context: C1 + 3-year intensity trend + sector median, P25 and P75.",
}


def sync_registry(session: Session, cfg: StudyConfig, models: ModelsConfig) -> dict[str, int]:
    """Upsert sectors, conditions and models. Returns row counts touched, for reporting."""
    for s in cfg.study.sectors:
        row = session.scalar(select(Sector).where(Sector.code == s.code))
        if row is None:
            session.add(Sector(code=s.code, name=s.name))
        else:
            row.name = s.name

    for code in cfg.runs.conditions:
        row = session.scalar(select(Condition).where(Condition.code == code))
        if row is None:
            session.add(Condition(code=code, description=CONDITION_TEXT[code]))

    for m in models.models:
        row = session.scalar(select(Model).where(Model.key == m.key))
        fields = {
            "role": m.role,
            "channel": m.channel,
            "vendor": m.vendor,
            "name": m.name,
            "provider": m.provider,
            "enabled": m.enabled,
        }
        if row is None:
            session.add(Model(key=m.key, **fields))
        else:
            for attr, value in fields.items():
                setattr(row, attr, value)
    sdg_count = sync_sdg_mapping(session, load_sdg_mapping(cfg, load_indicators(cfg)))
    session.flush()
    return {
        "sectors": len(cfg.study.sectors),
        "conditions": len(cfg.runs.conditions),
        "models": len(models.models),
        "sdg_mappings": sdg_count,
    }
