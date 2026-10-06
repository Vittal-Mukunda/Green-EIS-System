from __future__ import annotations

import pytest
import yaml
from sqlalchemy import func, select

from gauge import vocab
from gauge.config import ConfigError, load_indicators, load_models, load_study
from gauge.db.models import SdgMapping
from gauge.db.session import session_scope
from gauge.registry import sync_registry
from gauge.sdg.mapping import SdgConfig, load_sdg_mapping, sync_sdg_mapping


@pytest.fixture
def cfg_ind(proj):
    cfg = load_study("config/study_dry.yaml")
    return cfg, load_indicators(cfg)


def test_repo_mapping_is_valid_and_covers_environmental_indicators(cfg_ind):
    cfg, ind = cfg_ind
    sdg = load_sdg_mapping(cfg, ind)
    covered = {m.code for m in sdg.mappings}
    expected = {i.code for i in ind.indicators if i.code != "revenue_from_operations"}
    expected |= {k.code for k in ind.kpis}
    assert covered == expected


def test_caption_is_the_required_wording(cfg_ind):
    cfg, ind = cfg_ind
    assert (
        load_sdg_mapping(cfg, ind).caption
        == vocab.SDG_CAPTION
        == ("mapping indicates relevance, not achievement")
    )


def test_core_pairings(cfg_ind):
    cfg, ind = cfg_ind
    by = {m.code: (m.sdg, m.target) for m in load_sdg_mapping(cfg, ind).mappings}
    assert by["renewable_share"] == (7, "7.2") and by["energy_renewable"] == (7, "7.2")
    assert by["water_intensity"] == (6, "6.4") and by["emissions_intensity"][0] == 13
    assert by["waste_recovery_rate"] == (12, "12.5")


def _write(proj, mutate):
    path = proj / "config" / "sdg_mapping.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: d.update(caption="shows SDG achievement"), "caption must be exactly"),
        (lambda d: d["mappings"][0].update(target="12.5"), "does not belong to SDG"),
        (lambda d: d["mappings"][0].update(sdg=18), "less than or equal to 17"),
        (lambda d: d["mappings"][0].update(code="not_an_indicator"), "unknown indicator"),
        (lambda d: d["mappings"].append(dict(d["mappings"][0])), "duplicate"),
        (lambda d: d["mappings"][0].update(extra=1), "Extra inputs"),
    ],
)
def test_invalid_mappings_rejected(proj, cfg_ind, mutate, message):
    cfg, ind = cfg_ind
    _write(proj, mutate)
    with pytest.raises(ConfigError, match=message):
        load_sdg_mapping(cfg, ind)


def test_init_seeds_the_table_idempotently(db):
    with session_scope(db.engine) as s:
        assert s.scalar(select(func.count()).select_from(SdgMapping)) == 13
        sync_registry(s, db.cfg, load_models(db.cfg))  # again
    with session_scope(db.engine) as s:
        assert s.scalar(select(func.count()).select_from(SdgMapping)) == 13
        row = s.scalar(select(SdgMapping).where(SdgMapping.indicator_code == "renewable_share"))
    assert (row.sdg_number, row.sdg_target) == (7, "7.2")
    assert "project author" in row.source  # provenance says whose reading this is


def test_sync_replaces_rows(db):
    sdg = SdgConfig(
        caption=vocab.SDG_CAPTION,
        mappings=[dict(code="energy_total", sdg=7, target="7.3", note="n")],
    )
    with session_scope(db.engine) as s:
        assert sync_sdg_mapping(s, sdg) == 1
    with session_scope(db.engine) as s:
        assert s.scalar(select(func.count()).select_from(SdgMapping)) == 1
