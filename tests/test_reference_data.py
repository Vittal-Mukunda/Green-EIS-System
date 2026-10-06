"""The candidate pool and the reference-file manifest."""

from __future__ import annotations

import csv
import hashlib
import re
from collections import defaultdict

import pytest

POOL_COLUMNS = [
    "sector",
    "pool",
    "amfi_rank",
    "company_name",
    "nse_symbol",
    "isin",
    "avg_mcap_cr",
    "amfi_category",
    "note",
]


@pytest.fixture(scope="module")
def pool():
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "data" / "reference" / "candidate_pool.csv"
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames == POOL_COLUMNS
        return list(reader)


def by_sector(pool, which):
    out = defaultdict(list)
    for r in pool:
        if r["pool"] == which:
            out[r["sector"]].append(r)
    return out


def test_every_configured_sector_has_exactly_the_configured_number_of_primaries(pool, real_cfg):
    primaries = by_sector(pool, "primary")
    for sector in real_cfg.study.sectors:
        assert len(primaries[sector.name]) == real_cfg.study.companies_per_sector, sector.name


def test_each_sector_has_spares(pool, real_cfg):
    spares = by_sector(pool, "spare")
    assert all(len(spares[s.name]) >= 2 for s in real_cfg.study.sectors)


def test_pool_names_only_configured_sectors_and_known_pools(pool, real_cfg):
    assert {r["sector"] for r in pool} == {s.name for s in real_cfg.study.sectors}
    assert {r["pool"] for r in pool} <= {"primary", "spare", "not_in_pool"}


def test_primary_means_largest_by_rank_among_eligible(pool):
    """Selection rule (spec 4.1): the largest by market cap. Every primary outranks every spare."""
    for sector in {r["sector"] for r in pool}:
        prim = [
            int(r["amfi_rank"]) for r in pool if r["sector"] == sector and r["pool"] == "primary"
        ]
        spare = [
            int(r["amfi_rank"]) for r in pool if r["sector"] == sector and r["pool"] == "spare"
        ]
        assert max(prim) < min(spare), sector


def test_market_cap_decreases_with_rank_and_ranks_are_unique(pool):
    ordered = sorted(pool, key=lambda r: int(r["amfi_rank"]))
    caps = [float(r["avg_mcap_cr"]) for r in ordered]
    assert caps == sorted(caps, reverse=True) and min(caps) > 0
    assert len({r["amfi_rank"] for r in pool}) == len(pool)


def test_identifiers_are_well_formed_and_unique(pool):
    assert len({r["nse_symbol"] for r in pool}) == len(pool)
    assert len({r["isin"] for r in pool}) == len(pool)
    assert all(re.fullmatch(r"INE[A-Z0-9]{6}\d{3}", r["isin"]) for r in pool)
    assert all(re.fullmatch(r"[A-Z0-9&-]+", r["nse_symbol"]) for r in pool)


def test_amfi_categories_agree_with_rank(pool):
    """SEBI: top 100 by average market cap are large, the next 150 mid, the rest small cap."""
    for r in pool:
        rank = int(r["amfi_rank"])
        expected = "Large Cap" if rank <= 100 else "Mid Cap" if rank <= 250 else "Small Cap"
        assert r["amfi_category"] == expected, r["nse_symbol"]


def test_excluded_companies_say_why_and_recollections_are_marked(pool):
    for r in pool:
        if r["pool"] == "not_in_pool":
            assert r["note"], f"{r['nse_symbol']} is left out without a reason"
        if re.search(r"\brecall|\bmerger|\blisted in", r["note"], re.I):
            assert "(unverified)" in r["note"], f"{r['nse_symbol']}: recollection not marked"


# ---- manifest of downloaded reference files -----------------------------------------------------
def test_manifest_lists_every_downloaded_file(repo_root):
    manifest = (repo_root / "docs" / "REFERENCE_FILES.md").read_text(encoding="utf-8")
    folder = repo_root / "data" / "raw" / "reference"
    if not folder.is_dir():
        pytest.skip("reference downloads are gitignored and absent in this checkout")
    for file in folder.glob("*.pdf"):
        assert file.name in manifest, f"{file.name} is not in docs/REFERENCE_FILES.md"
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        assert digest in manifest, f"{file.name}: SHA-256 differs from the manifest"


def test_manifest_hashes_are_well_formed(repo_root):
    manifest = (repo_root / "docs" / "REFERENCE_FILES.md").read_text(encoding="utf-8")
    hashes = re.findall(r"`([0-9a-f]{64})`", manifest)
    assert len(hashes) == len(set(hashes)) == 5


def test_checklist_names_every_primary(pool, repo_root):
    text = (repo_root / "docs" / "DOWNLOAD_CHECKLIST.md").read_text(encoding="utf-8")
    for r in pool:
        if r["pool"] == "primary":
            assert f"`{r['nse_symbol']}`" in text, r["nse_symbol"]
