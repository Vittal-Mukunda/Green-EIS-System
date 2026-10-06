"""Synthetic scaffolding for dry runs. Nothing here describes real companies or real data."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from gauge.config import StudyConfig
from gauge.db.models import Company, Sector

# Known defects the MockRunner injects in dry runs, so the parse/evaluate stages always have
# something to catch (one of each kind).
DRY_FORCED_ERRORS = {
    "P1_C1_r1": "long_justification",
    "P2_C1_r2": "out_of_range_rating",
    "P3_C2_r1": "truncated",
    "P4_C2_r2": "wrong_type",
    "B1_C1_r1": "missing_company",
}


def seed_synthetic_companies(session: Session, cfg: StudyConfig) -> int:
    """Create masked synthetic companies for every configured sector (idempotent)."""
    created = 0
    for sector_cfg in cfg.study.sectors:
        sector = session.scalar(select(Sector).where(Sector.code == sector_cfg.code))
        if sector is None:
            raise LookupError("sectors not registered: run sync_registry first")
        for i in range(1, cfg.study.companies_per_sector + 1):
            code = f"{sector_cfg.code}-{i:02d}"
            if session.scalar(select(Company).where(Company.code == code)) is None:
                session.add(
                    Company(
                        code=code,
                        real_name=f"Synthetic Company {code}",
                        sector_id=sector.id,
                        selection_status="included",
                        is_synthetic=True,
                    )
                )
                created += 1
    session.flush()
    return created


def placeholder_prompt(condition: str, company_codes: list[str]) -> str:
    """Stand-in prompt for Phase 1 dry runs; real C1/C2 prompts come from the Phase 4 renderer."""
    header = (
        f"PHASE-1 PLACEHOLDER PROMPT, condition {condition}. This is not a study prompt.\n"
        "Return a JSON array with one object per company below.\n"
    )
    return (
        header
        + "\n".join(f"## {code}\n(no evidence: placeholder)" for code in company_codes)
        + "\n"
    )
