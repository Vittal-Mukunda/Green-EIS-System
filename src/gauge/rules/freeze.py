"""Freeze the rules and prompt templates (spec hard rule 7) and verify the freeze later.

The manifest `registry/frozen_manifest.json` records:
  * the SHA-256 of every frozen file: both rule files, the three prompt templates and
    config/indicators.yaml (its labels and formulas are printed in the prompts);
  * the SHA-256 of the fully rendered prompt of EVERY planned run, with its company order, so a
    change to the data, the sample, the rounding or the renderer after the freeze is caught too.

`gauge run` calls `verify_frozen` first and refuses to start if anything differs.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from gauge.config import IndicatorsConfig, ModelsConfig, StudyConfig
from gauge.db.models import Condition, PromptTemplate, Rule, Run
from gauge.render.prompts import TEMPLATE_FILES, USER_FILES, RenderError, templates_dir
from gauge.render.runs import prepare_render, render_run_prompts
from gauge.rules.build import T2_RULE_ID, T3_RULE_ID, RuleFileError, load_t3_rule, t2_path, t3_path

MANIFEST_VERSION = 1


class FreezeError(RuntimeError):
    """Freezing is refused, or the frozen files no longer match the manifest."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_path(cfg: StudyConfig) -> Path:
    return cfg.path(cfg.paths.frozen_manifest)


def frozen_file_paths(cfg: StudyConfig) -> dict[str, Path]:
    """Frozen files by manifest key (a path relative to the project root, with forward slashes)."""
    folder = templates_dir(cfg)
    paths = [t2_path(cfg), t3_path(cfg), *[folder / name for name in TEMPLATE_FILES]]
    paths.append(cfg.path(cfg.paths.indicators_file))
    return {p.resolve().relative_to(cfg.root.resolve()).as_posix(): p for p in paths}


def read_manifest(cfg: StudyConfig) -> dict:
    path = manifest_path(cfg)
    if not path.is_file():
        raise FreezeError(f"not frozen: {path} does not exist (run `gauge freeze`)")
    return json.loads(path.read_text(encoding="utf-8"))


def is_frozen(cfg: StudyConfig) -> bool:
    return manifest_path(cfg).is_file()


# ---- DB rows for rules and templates ---------------------------------------------------
def register_files(
    session: Session, cfg: StudyConfig, *, frozen_utc: datetime | None = None
) -> int:
    """Upsert the `rule` and `prompt_template` rows from the files on disk; returns rows touched.

    With `frozen_utc` the rows are stamped frozen. Missing files are skipped (not an error here).
    """
    touched = 0
    root = cfg.root.resolve()
    for rule_id, kind, path in (
        (T2_RULE_ID, "T2", t2_path(cfg)),
        (T3_RULE_ID, "T3_UPDATE", t3_path(cfg)),
    ):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        row = session.scalar(select(Rule).where(Rule.rule_id == rule_id))
        if row is None:
            row = Rule(rule_id=rule_id, kind=kind, path="", sha256="", content="")
            session.add(row)
        row.path = path.resolve().relative_to(root).as_posix()
        row.sha256, row.content = sha256_file(path), text
        if frozen_utc is not None:
            row.frozen_utc = frozen_utc
        touched += 1

    conditions = {c.code: c.id for c in session.scalars(select(Condition))}
    by_file = {name: cond for cond, name in USER_FILES.items()}
    for name in TEMPLATE_FILES:
        path = templates_dir(cfg) / name
        if not path.is_file():
            continue
        stem = path.stem
        row = session.scalar(select(PromptTemplate).where(PromptTemplate.name == stem))
        if row is None:
            row = PromptTemplate(name=stem, path="", sha256="", content="")
            session.add(row)
        row.condition_id = conditions.get(by_file.get(name, ""))
        row.path = path.resolve().relative_to(root).as_posix()
        row.sha256, row.content = sha256_file(path), path.read_text(encoding="utf-8")
        if frozen_utc is not None:
            row.frozen_utc = frozen_utc
        touched += 1
    session.flush()
    return touched


def _runs_exist(session: Session) -> bool:
    return bool(session.scalar(select(func.count()).select_from(Run)))


def ensure_not_frozen(session: Session, cfg: StudyConfig, *, force: bool = False) -> None:
    """Guard for commands that would change frozen files (build-rules)."""
    if not is_frozen(cfg):
        return
    if _runs_exist(session):
        raise FreezeError("the rules are frozen and runs exist: they can no longer be rebuilt")
    if not force:
        raise FreezeError(
            f"the rules are frozen ({manifest_path(cfg)} exists); rebuilding them needs --force, "
            "and the prompts must then be reviewed and frozen again"
        )


# ---- freeze --------------------------------------------------------------------------------------
@dataclass
class FreezeResult:
    manifest: Path
    files: dict[str, str]
    prompts: int
    companies: int
    warnings: list[str] = field(default_factory=list)


def freeze(
    session: Session,
    cfg: StudyConfig,
    indicators: IndicatorsConfig,
    models: ModelsConfig,
    *,
    force: bool = False,
) -> FreezeResult:
    """Render every run's prompt, then write the manifest. Refuses anything provisional or stale."""
    if is_frozen(cfg):
        if _runs_exist(session):
            raise FreezeError("already frozen and runs exist: the freeze can no longer change")
        if not force:
            raise FreezeError(
                f"already frozen ({manifest_path(cfg)}); `gauge freeze --force` re-freezes "
                "(allowed only while no run exists)"
            )

    for label, path in (("T2 rule", t2_path(cfg)), ("T3 update rule", t3_path(cfg))):
        if not path.is_file():
            raise FreezeError(f"{label} file missing: {path} (run `gauge build-rules`)")
    try:
        load_t3_rule(t3_path(cfg))
        ctx = prepare_render(session, cfg, indicators)  # checks the T2 file against the benchmarks
        run_prompts = render_run_prompts(cfg, indicators, models, ctx, include_disabled=True)
    except (RuleFileError, RenderError) as exc:
        raise FreezeError(f"cannot freeze: {exc}") from exc
    if ctx.evidence.n_not_reported and not ctx.evidence.synthetic:
        raise FreezeError(
            f"cannot freeze: {ctx.evidence.n_not_reported} value(s) in the real sample would print "
            "as 'not reported'; selection should guarantee complete indicators (run `gauge select`)"
        )

    files = {key: sha256_file(path) for key, path in frozen_file_paths(cfg).items()}
    now = datetime.now(UTC)
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "frozen_utc": now.isoformat(timespec="seconds"),
        "analysis_fy": cfg.study.analysis_fy,
        "trend_fys": list(cfg.study.trend_fys),
        "companies": sorted(ctx.evidence.companies),
        "files": files,
        "prompts": {
            rp.planned.run_id: {
                "condition": rp.planned.condition,
                "sha256": rp.prompt.sha256,
                "system_sha256": rp.prompt.system_sha256,
                "user_sha256": rp.prompt.user_sha256,
                "company_order": list(rp.prompt.company_order),
            }
            for rp in run_prompts
        },
    }
    path = manifest_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(manifest, indent=2, sort_keys=False) + "\n").encode("utf-8"))
    register_files(session, cfg, frozen_utc=now)
    return FreezeResult(path, files, len(run_prompts), len(ctx.evidence.companies))


# ---- verification --------------------------------------------------------------------------------
def verify_frozen(
    cfg: StudyConfig,
    session: Session | None = None,
    indicators: IndicatorsConfig | None = None,
    models: ModelsConfig | None = None,
) -> list[str]:
    """Problems found (empty list = intact). File hashes always; with a session, indicators and
    models, every prompt is rendered again and compared with the manifest."""
    try:
        manifest = read_manifest(cfg)
    except (FreezeError, json.JSONDecodeError) as exc:
        return [str(exc)]
    problems = []
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        problems.append(f"manifest version {manifest.get('manifest_version')} is not supported")
    current = frozen_file_paths(cfg)
    for key, expected in manifest.get("files", {}).items():
        path = current.get(key) or cfg.path(key)
        if not path.is_file():
            problems.append(f"{key}: frozen file is missing")
        elif sha256_file(path) != expected:
            problems.append(f"{key}: changed since the freeze")
    for key in current.keys() - manifest.get("files", {}).keys():
        problems.append(f"{key}: not listed in the manifest")

    if session is not None and indicators is not None and models is not None and not problems:
        try:
            ctx = prepare_render(session, cfg, indicators)
            rendered = {
                rp.planned.run_id: rp
                for rp in render_run_prompts(cfg, indicators, models, ctx, include_disabled=True)
            }
        except RenderError as exc:
            return [f"cannot re-render the prompts: {exc}"]
        frozen = manifest.get("prompts", {})
        for run_id in sorted(frozen.keys() - rendered.keys()):
            problems.append(f"{run_id}: in the manifest but no longer planned")
        for run_id in sorted(rendered.keys() - frozen.keys()):
            problems.append(f"{run_id}: planned but not in the manifest")
        for run_id in sorted(frozen.keys() & rendered.keys()):
            if rendered[run_id].prompt.sha256 != frozen[run_id]["sha256"]:
                problems.append(f"{run_id}: the rendered prompt differs from the frozen one")
    return problems


def assert_frozen_ok(
    cfg: StudyConfig,
    session: Session | None = None,
    indicators: IndicatorsConfig | None = None,
    models: ModelsConfig | None = None,
) -> None:
    problems = verify_frozen(cfg, session, indicators, models)
    if problems:
        raise FreezeError("frozen files do not match the manifest:\n  " + "\n  ".join(problems))
