"""Repository hygiene: layout (§3), sandbox rule, secrets, and the §11 'never claim' guard."""

from __future__ import annotations

import re

import pytest

SUBPACKAGES = [
    "db",
    "ingest",
    "standardize",
    "quality",
    "kpi",
    "benchmark",
    "sdg",
    "rules",
    "render",
    "runner",
    "parse",
    "evaluate",
    "msa",
    "stats",
]
REQUIRED_DIRS = [
    "config",
    "data/raw",
    "data/processed",
    "registry/rules",
    "registry/prompts",
    "runs/prompts",
    "runs/raw",
    "runs/manual_inbox",
    "runs/sandbox",
    "dashboard",
    "notebooks",
    "tests",
    "docs",
    *[f"src/gauge/{p}" for p in SUBPACKAGES],
]
REQUIRED_FILES = [
    "CLAUDE.md",
    "README.md",
    "Makefile",
    "tasks.py",
    "pyproject.toml",
    "requirements.txt",
    ".gitignore",
    ".env.example",
    "config/study.yaml",
    "config/models.yaml",
    "config/indicators.yaml",
    "data/manual_entry_template.csv",
    "dashboard/app.py",
    "notebooks/analysis.ipynb",
    "src/gauge/cli.py",
    "docs/METHODS.md",
    "docs/RUNNER.md",
    "docs/DATA_SOURCES.md",
    "docs/VERIFY.md",
    "docs/schema.sql",
    "docs/BUILD_SPEC.md",
    "docs/REFERENCE_FILES.md",
    "docs/DOWNLOAD_CHECKLIST.md",
    "data/reference/candidate_pool.csv",
    "data/reference/pdf_manifest.csv",
    "config/xbrl_mapping.yaml",
    "config/xbrl_overrides.yaml",
]


@pytest.mark.parametrize("rel", REQUIRED_DIRS)
def test_required_directories_exist(repo_root, rel):
    assert (repo_root / rel).is_dir()


@pytest.mark.parametrize("rel", REQUIRED_FILES)
def test_required_files_exist(repo_root, rel):
    assert (repo_root / rel).is_file()


def test_sandbox_is_empty_and_has_no_cursor_rules(repo_root):
    """Hard rule 1: nothing in runs/sandbox/ may leak into a model's context."""
    assert list((repo_root / "runs/sandbox").iterdir()) == []


def test_secrets_are_gitignored_and_not_committed(repo_root):
    ignore = (repo_root / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignore and "data/raw/*" in ignore
    example = (repo_root / ".env.example").read_text(encoding="utf-8")
    assert re.search(
        r"^OPENROUTER_API_KEY=$", example, re.M
    )  # blank: no key ever lands in the repo


def test_manual_entry_template_header(repo_root):
    header = (repo_root / "data/manual_entry_template.csv").read_text(encoding="utf-8").splitlines()
    assert header == [
        "company,nse_symbol,sector,fy,indicator,value,unit,boundary,assured,source_url,page_ref"
    ]


def test_claude_md_summarises_required_sections(repo_root):
    text = (repo_root / "CLAUDE.md").read_text(encoding="utf-8")
    for heading in (
        "## 0. Context",
        "## 2. Hard rules",
        "## 4. Study design",
        "## 11. Never claim",
    ):
        assert heading in text


# §11: phrases that must not appear in code, docs we write, or the dashboard.
FORBIDDEN = [
    r"\bthe model (thinks|believes|feels|wants|understands)\b",
    r"\bhas a perspective\b",
    r"\bBRSR data (is|are) (fully )?reliable\b",
    r"\bshows? (SDG )?achievement\b",
    r"\bgreener company because\b",
    r"\bjustification explains (why|the decision)\b",
]


def test_never_claim_guard(repo_root):
    files = [
        *repo_root.joinpath("src").rglob("*.py"),
        *repo_root.joinpath("dashboard").rglob("*.py"),
        *(p for p in repo_root.joinpath("docs").glob("*.md") if p.name != "BUILD_SPEC.md"),
    ]
    offenders = [
        (f.name, pat)
        for f in files
        for pat in FORBIDDEN
        if re.search(pat, f.read_text(encoding="utf-8"), re.I)
    ]
    assert offenders == []


def test_no_stray_control_characters(repo_root):
    """A mangled backslash escape once put control characters into the README."""
    bad_chars = {chr(c) for c in (*range(0, 9), 11, 12, *range(14, 32))} | {"\r"}
    files = [
        *repo_root.joinpath("src").rglob("*.py"),
        *repo_root.joinpath("tests").glob("*.py"),
        *repo_root.joinpath("docs").glob("*.md"),
        *repo_root.joinpath("config").glob("*.yaml"),
        repo_root / "README.md",
        repo_root / "CLAUDE.md",
    ]
    offenders = {
        f.name: sorted({repr(c) for c in bad_chars if c in text})
        for f in files
        if (text := f.read_bytes().decode("utf-8")) and bad_chars & set(text)
    }
    assert offenders == {}
