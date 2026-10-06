"""`gauge` command line (spec §8).

Every command of the spec is implemented. `run` and `smoke` are the only ones that can make a real
model call, and both refuse to start unless their checks pass and the owner confirms.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import date
from enum import StrEnum
from pathlib import Path

import typer
from dotenv import load_dotenv
from sqlalchemy import Engine
from sqlalchemy.engine import make_url

from gauge import __version__
from gauge.config import (
    ConfigError,
    IndicatorsConfig,
    ModelsConfig,
    StudyConfig,
    load_indicators,
    load_models,
    load_study,
    project_root,
)
from gauge.db.ddl import write_ddl_files
from gauge.db.session import init_db, make_engine, session_scope
from gauge.ingest.manual import parse_manual_csv
from gauge.ingest.xbrl import read_instance, summarize, write_facts_csv
from gauge.pipeline import DRY_CONFIG, DryRunError, run_all_dry
from gauge.registry import sync_registry
from gauge.rules.freeze import verify_frozen
from gauge.stages import (
    StageResult,
    stage_benchmarks,
    stage_build_rules,
    stage_compute_kpis,
    stage_freeze,
    stage_ingest_manual,
    stage_ingest_xbrl,
    stage_render,
    stage_standardize,
    stage_validate,
    stage_verify_frozen,
)

app = typer.Typer(
    name="gauge",
    help="LLM Gauge: Green EIS for measurement-system analysis of multi-LLM BRSR interpretation.",
    no_args_is_help=True,
    add_completion=False,
)


class RunMode(StrEnum):
    cli = "cli"
    manual = "manual"
    api = "api"


def _load(ctx: typer.Context) -> StudyConfig:
    try:
        return load_study(ctx.obj["config"])
    except ConfigError as exc:
        typer.echo(f"config error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


def _load_indicators(cfg: StudyConfig) -> IndicatorsConfig:
    try:
        return load_indicators(cfg)
    except ConfigError as exc:
        typer.echo(f"config error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


def _load_models(cfg: StudyConfig) -> ModelsConfig:
    try:
        return load_models(cfg)
    except ConfigError as exc:
        typer.echo(f"config error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


def _engine(cfg: StudyConfig) -> Engine:
    """Engine for an existing database; refuses to create an empty one by accident."""
    url = make_url(cfg.database_url())
    if url.get_backend_name() == "sqlite" and url.database and not Path(url.database).is_file():
        typer.echo("database not found: run `gauge init-db` first", err=True)
        raise typer.Exit(code=1)
    return make_engine(cfg.database_url())


def _resolve(cfg: StudyConfig, path: Path) -> Path:
    """A path as given if it exists, else relative to the project root."""
    return path if path.is_absolute() or path.exists() else cfg.root / path


def _parse_date(text: str | None) -> date | None:
    """--retrieved-on: an ISO date, or None (left empty, with a note: it is never guessed)."""
    if not text:
        typer.echo("note: no --retrieved-on given; the retrieval date is left empty", err=True)
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise typer.BadParameter("--retrieved-on must be YYYY-MM-DD") from exc


def _report(result: StageResult) -> None:
    mark = {"ok": "ok     ", "pending": "pending", "error": "ERROR  "}[result.status]
    typer.echo(f"[{mark}] {result.name:<15} {result.detail}")
    if result.status == "error":
        raise typer.Exit(code=1)


@app.callback()
def main(
    ctx: typer.Context,
    config: str = typer.Option(
        "config/study.yaml", "--config", "-c", help="Study config, relative to the project root."
    ),
    version: bool = typer.Option(False, "--version", help="Show version and exit.", is_eager=True),
) -> None:
    if version:
        typer.echo(f"gauge {__version__}")
        raise typer.Exit()
    load_dotenv(project_root() / ".env")  # API keys live in .env (gitignored); never printed
    ctx.obj = {"config": config}


# ---- implemented in Phase 1 ------------------------------------------------------------------
@app.command("init-db")
def init_db_cmd(
    ctx: typer.Context,
    ddl_only: bool = typer.Option(
        False, "--ddl-only", help="Only (re)write docs/schema.sql and docs/schema_postgres.sql."
    ),
) -> None:
    """Create the database schema and register sectors, conditions and models from config."""
    cfg = _load(ctx)
    if ddl_only:
        for path in write_ddl_files(cfg.root / "docs"):
            typer.echo(f"wrote {path.relative_to(cfg.root)}")
        return
    models = load_models(cfg)
    engine = make_engine(cfg.database_url())
    tables = init_db(engine)
    with session_scope(engine) as session:
        counts = sync_registry(session, cfg, models)
    typer.echo(f"database ready: {cfg.paths.database_url} ({len(tables)} tables)")
    typer.echo("registered: " + ", ".join(f"{n} {k}" for k, n in counts.items()))


@app.command("all-dry")
def all_dry(
    config: str = typer.Option(DRY_CONFIG, "--config", help="Dry-run config (mock models only)."),
) -> None:
    """Run every built stage on synthetic data with the MockRunner. Never calls Cursor."""

    def show(r: StageResult) -> None:
        mark = {"ok": "ok     ", "pending": "pending", "error": "ERROR  "}[r.status]
        typer.echo(f"[{mark}] {r.name:<15} {r.detail}")

    try:
        results = run_all_dry(config, log=show)
    except (ConfigError, DryRunError) as exc:
        typer.echo(f"dry run refused: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    pending = [r.name for r in results if r.status == "pending"]
    typer.echo(
        f"\ndry run finished: {len(results) - len(pending)} stages ok, {len(pending)} pending"
    )


@app.command()
def dashboard(ctx: typer.Context) -> None:
    """Launch the Streamlit dashboard (the page itself is a placeholder until Phase 7)."""
    cfg = _load(ctx)
    app_path = cfg.root / "dashboard" / "app.py"
    env_config = ctx.obj["config"]
    cmd = [sys.executable, "-m", "streamlit", "run", str(app_path), "--", "--config", env_config]
    raise typer.Exit(code=subprocess.call(cmd))


# ---- data pipeline (Phase 2) -----------------------------------------------------------------
@app.command()
def ingest(
    ctx: typer.Context,
    manual: Path | None = typer.Option(
        None, "--manual", help="Manual-entry CSV (data/manual_entry_template.csv format)."
    ),
    validate_only: bool = typer.Option(
        False, "--validate-only", help="With --manual: check the file and report, load nothing."
    ),
    retrieved_on: str | None = typer.Option(
        None, "--retrieved-on", help="Date (YYYY-MM-DD) you retrieved the filings."
    ),
    xbrl: list[Path] | None = typer.Option(
        None, "--xbrl", help="BRSR XBRL file or folder to load (repeatable)."
    ),
    inspect_xbrl: Path | None = typer.Option(
        None, "--inspect-xbrl", help="Summarize a downloaded BRSR XBRL instance (loads nothing)."
    ),
    facts_csv: Path | None = typer.Option(
        None, "--facts-csv", help="With --inspect-xbrl: also write every fact to this CSV."
    ),
) -> None:
    """Ingest BRSR data from XBRL filings (--xbrl) or a manual-entry CSV (--manual), or inspect one
    XBRL file (--inspect-xbrl). Nothing here downloads anything.
    """
    cfg = _load(ctx)
    if sum(x is not None for x in (manual, inspect_xbrl, xbrl or None)) != 1:
        raise typer.BadParameter("give exactly one of --xbrl, --manual or --inspect-xbrl")

    if xbrl:
        when = _parse_date(retrieved_on)
        indicators = _load_indicators(cfg)
        paths = [_resolve(cfg, p) for p in xbrl]
        try:
            result = stage_ingest_xbrl(_engine(cfg), cfg, indicators, paths, retrieved_on=when)
        except (ConfigError, FileNotFoundError) as exc:
            typer.echo(f"config error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        _report(result)
        return

    if inspect_xbrl is not None:
        path = _resolve(cfg, inspect_xbrl)
        inst = read_instance(path)
        typer.echo(summarize(inst))
        if facts_csv is not None:
            n = write_facts_csv(inst, _resolve(cfg, facts_csv))
            typer.echo(f"\nwrote {n} facts to {facts_csv}")
        return

    indicators = _load_indicators(cfg)
    path = _resolve(cfg, manual)
    if validate_only:
        parsed = parse_manual_csv(path, cfg, indicators)
        for issue in parsed.issues:
            typer.echo(str(issue))
        typer.echo(f"{len(parsed.rows)} valid rows, {len(parsed.errors)} errors")
        raise typer.Exit(code=0 if parsed.ok else 1)
    when = _parse_date(retrieved_on)
    _report(stage_ingest_manual(_engine(cfg), cfg, indicators, path, retrieved_on=when))


@app.command()
def standardize(ctx: typer.Context) -> None:
    """Convert units to canonical form (as-reported values are kept for audit)."""
    cfg = _load(ctx)
    _report(stage_standardize(_engine(cfg), _load_indicators(cfg)))


@app.command()
def validate(
    ctx: typer.Context,
    strict: bool = typer.Option(False, "--strict", help="Exit 1 if any error-level flag exists."),
) -> None:
    """Run the data-quality validators and store flags (replaces the previous set)."""
    cfg = _load(ctx)
    engine = _engine(cfg)
    result = stage_validate(engine, cfg, _load_indicators(cfg))
    _report(result)
    if strict and result.data["errors"]:
        raise typer.Exit(code=1)


@app.command("compute-kpis")
def compute_kpis(ctx: typer.Context) -> None:
    """Compute deterministic KPIs and 2-year changes (rebuilds all KPI values)."""
    cfg = _load(ctx)
    _report(stage_compute_kpis(_engine(cfg), cfg, _load_indicators(cfg)))


@app.command()
def benchmarks(ctx: typer.Context) -> None:
    """Compute sector median / P25 / P75 and tertile cut-points for `included` companies."""
    cfg = _load(ctx)
    _report(stage_benchmarks(_engine(cfg), cfg, _load_indicators(cfg)))


# ---- later phases ----------------------------------------------------------------------------
@app.command()
def select(
    ctx: typer.Context,
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show the selection without changing anything."
    ),
    no_renumber: bool = typer.Option(
        False, "--no-renumber", help="Keep the existing masked codes."
    ),
) -> None:
    """Choose the study sample from the candidate pool (largest by market cap, complete indicators).

    Marks companies included/excluded (every exclusion keeps its reason) and, once complete, gives
    the included companies the codes SEC-01..SEC-N. Refuses while a trend year is not loaded.
    """
    from gauge.ingest.pool import load_pool
    from gauge.ingest.select import SelectionError, run_selection

    cfg = _load(ctx)
    indicators = _load_indicators(cfg)
    engine = _engine(cfg)
    try:
        with session_scope(engine) as session:
            result = run_selection(
                session,
                cfg,
                indicators,
                load_pool(cfg.root),
                apply=not dry_run,
                renumber=not no_renumber,
            )
    except (SelectionError, FileNotFoundError) as exc:
        typer.echo(f"selection not run: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    for o in result.sectors:
        typer.echo(
            f"{o.sector:<13} included {len(o.included)}/{cfg.study.companies_per_sector}: "
            f"{', '.join(o.included)}"
        )
        for symbol, reason in o.excluded.items():
            typer.echo(f"    excluded {symbol}: {reason}")
        if o.wanted_spares:
            typer.echo(f"    needs data for spare(s): {', '.join(o.wanted_spares)}")
    if result.renumbered:
        typer.echo(f"renumbered {len(result.renumbered)} masked codes: {result.renumbered}")
    typer.echo("sample complete" if result.complete else "SAMPLE INCOMPLETE: see the lines above")
    raise typer.Exit(code=0 if result.complete else 1)


@app.command("verify-sample")
def verify_sample(
    ctx: typer.Context,
    fraction: float = typer.Option(
        0.10, "--fraction", min=0.01, max=1.0, help="Share of each company's values."
    ),
    seed: int = typer.Option(
        42, "--seed", help="Sampling seed (the same seed gives the same sample)."
    ),
    out: Path = typer.Option(
        Path("data/processed/verify_sample.csv"), "--out", help="Where to write the checklist."
    ),
    record: Path | None = typer.Option(
        None,
        "--record",
        help="Instead of drawing: store the human_result column of a filled-in CSV.",
    ),
    accept_auto_found: bool = typer.Option(
        False,
        "--accept-auto-found",
        help="With --record: count blank rows the PDF search found as ok.",
    ),
) -> None:
    """Draw a seeded sample of stored values to check against filing PDFs, or record the results.

    Each row names the XBRL element and the PDF; where the PDF is on file the value is searched for
    in its text and the page is suggested. Only `human_result` = ok/error marks a value verified.
    """
    from gauge.quality.verify import auto_check, draw_sample, record_results, write_csv

    cfg = _load(ctx)
    engine = _engine(cfg)
    if record is not None:
        with session_scope(engine) as session:
            summary = record_results(
                session, _resolve(cfg, record), accept_auto_found=accept_auto_found
            )
        rate = "n/a" if summary.error_rate is None else f"{summary.error_rate:.1%}"
        typer.echo(
            f"recorded {summary.ok} ok, {summary.error} errors ({rate} error rate); "
            f"{summary.pending} left blank"
        )
        raise typer.Exit(code=1 if summary.error else 0)
    with session_scope(engine) as session:
        items = draw_sample(session, cfg.root, fraction=fraction, seed=seed)
    if not items:
        typer.echo("no real values in the database yet: run `gauge ingest` first", err=True)
        raise typer.Exit(code=1)
    items = auto_check(items, cfg.root)
    target = out if out.is_absolute() else cfg.root / out
    write_csv(items, target)
    found = sum(i.auto_check.startswith("found on") for i in items)
    typer.echo(
        f"{len(items)} values sampled ({len({i.company_code for i in items})} companies), "
        f"{found} found in their PDF automatically; wrote {target}"
    )
    typer.echo(
        "Fill in human_result (ok or error) and human_note, then run: "
        "gauge verify-sample --record <file>"
    )


@app.command("build-rules")
def build_rules(
    ctx: typer.Context,
    provisional: bool = typer.Option(
        False,
        "--provisional",
        help="Preview the T2 rule from candidates into runs/provisional/ (nothing frozen).",
    ),
    force: bool = typer.Option(
        False, "--force", help="Rebuild frozen rules (refused once any run exists)."
    ),
) -> None:
    """Build the T2 rule (with sector cut-points) and the T3 update rule into registry/rules/."""
    cfg = _load(ctx)
    _report(
        stage_build_rules(
            _engine(cfg), cfg, _load_indicators(cfg), provisional=provisional, force=force
        )
    )


class ConditionChoice(StrEnum):
    C1 = "C1"
    C2 = "C2"
    both = "both"


@app.command()
def render(
    ctx: typer.Context,
    condition: ConditionChoice = typer.Option(
        ConditionChoice.both, "--condition", help="Which condition to render."
    ),
    provisional: bool = typer.Option(
        False,
        "--provisional",
        help="Use candidate companies (a preview, written to runs/provisional/, never frozen).",
    ),
    sample: bool = typer.Option(
        False, "--sample", help="Write ONE full prompt per condition to --out for review."
    ),
    out: Path = typer.Option(
        Path("runs/prompts/sample_prompts.md"), "--out", help="Where --sample writes."
    ),
) -> None:
    """Render the prompt of every planned run to runs/prompts/ (with index.csv), or a sample."""
    cfg = _load(ctx)
    indicators = _load_indicators(cfg)
    engine = _engine(cfg)
    conditions = ("C1", "C2") if condition is ConditionChoice.both else (condition.value,)
    if not sample:
        _report(
            stage_render(
                engine, cfg, indicators, _load_models(cfg), provisional=provisional,
                conditions=conditions,
            )
        )  # fmt: skip
        return
    from gauge.render.prompts import RenderError
    from gauge.render.runs import prepare_render
    from gauge.render.sample import sample_section

    try:
        with session_scope(engine) as session:
            rctx = prepare_render(
                session, cfg, indicators, provisional=provisional, with_trend="C2" in conditions
            )
            text = sample_section(cfg, indicators, rctx, conditions, heading="Sample prompts")
    except RenderError as exc:
        typer.echo(f"render failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    target = out if out.is_absolute() else cfg.root / out
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(("# Sample prompts\n\n" + text).encode("utf-8"))
    typer.echo(f"wrote {target}")


@app.command()
def freeze(
    ctx: typer.Context,
    force: bool = typer.Option(
        False, "--force", help="Freeze again (refused once any run exists)."
    ),
    verify: bool = typer.Option(
        False, "--verify", help="Only check that frozen files and rendered prompts still match."
    ),
) -> None:
    """Freeze rules and prompt templates (SHA-256 manifest). Run it only after reviewing the
    sample prompts: the runner refuses to start if a frozen file changes afterwards."""
    cfg = _load(ctx)
    indicators, engine = _load_indicators(cfg), _engine(cfg)
    models = _load_models(cfg)
    if verify:
        _report(stage_verify_frozen(engine, cfg, indicators, models))
        return
    _report(stage_freeze(engine, cfg, indicators, models, force=force))


def _split_keys(text: str | None) -> list[str] | None:
    return [k.strip() for k in text.split(",") if k.strip()] if text else None


@app.command()
def run(
    ctx: typer.Context,
    mode: RunMode = typer.Option(
        ..., "--mode", help="cli (Cursor), manual (paste), api (baseline)."
    ),
    force: bool = typer.Option(
        False, "--force", help="Re-run even if a successful raw file exists."
    ),
    only: str | None = typer.Option(
        None, "--only", help="Comma-separated model keys to run, e.g. P1,P2."
    ),
    limit: int | None = typer.Option(
        None, "--limit", min=1, help="Make at most this many calls, then stop."
    ),
    yes: bool = typer.Option(False, "--yes", help="Do not ask before real model calls."),
) -> None:
    """Execute pending runs: cli = Cursor agent, api = free-tier baseline, manual = instructions.

    Refuses to start unless the frozen files and every rendered prompt still match the manifest, the
    model names are real, and the channel is ready (sandbox empty, CLI model list, API key and model
    id). Resumable: run the same command again after a stop. Exit code 3 = stopped early, resume.
    """
    from gauge.render.prompts import RenderError
    from gauge.render.runs import prepare_render
    from gauge.runcmd import manual_instructions, select_runs
    from gauge.runner.api import ApiConfigError
    from gauge.runner.cursor import CursorLaunchError
    from gauge.runner.factory import build_runner, preflight
    from gauge.runner.orchestrate import run_pending

    cfg = _load(ctx)
    indicators, models = _load_indicators(cfg), _load_models(cfg)
    engine = _engine(cfg)
    try:
        with session_scope(engine) as session:
            rctx = prepare_render(session, cfg, indicators)
            selected = select_runs(cfg, indicators, models, rctx, mode.value, _split_keys(only))
    except RenderError as exc:
        typer.echo(f"cannot start: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if not selected:
        typer.echo("no planned runs for this mode (check --only and config/models.yaml)", err=True)
        raise typer.Exit(code=1)

    if mode is RunMode.manual:
        with session_scope(engine) as session:
            problems = verify_frozen(cfg, session, indicators, models)
            if problems:
                typer.echo(
                    "frozen files do not match the manifest:\n  " + "\n  ".join(problems), err=True
                )
                raise typer.Exit(code=1)
            blocks, done = manual_instructions(session, cfg, selected)
        typer.echo(f"{len(blocks)} manual run(s) to do, {done} already imported.\n")
        typer.echo("\n\n".join(blocks))
        typer.echo(
            f"\nAfter saving the replies to {cfg.manual_inbox_dir}: "
            "gauge import-manual, then gauge parse"
        )
        return

    try:
        runner = build_runner(mode.value, cfg, models)
    except (CursorLaunchError, ApiConfigError) as exc:
        typer.echo(f"cannot start: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    with session_scope(engine) as session:
        report = preflight(session, cfg, indicators, models, mode.value, selected, runner=runner)
    for line in report.info:
        typer.echo(line)
    if not report.ok:
        typer.echo("NOT starting:\n  " + "\n  ".join(report.problems), err=True)
        raise typer.Exit(code=1)
    if not yes and not typer.confirm(
        f"{len(selected)} planned run(s) through the {mode.value} channel use real model calls "
        "(your quota). Start?"
    ):
        raise typer.Exit(code=1)

    summary = run_pending(
        engine, cfg, selected, runner, force=force, log=typer.echo, max_runs=limit
    )
    typer.echo(
        f"{summary.executed} executed, {summary.skipped} skipped, {summary.failed} failed"
        + (f"; stopped: {summary.stopped}" if summary.stopped else "")
        + ("; limit reached" if summary.limited else "")
    )
    if summary.stopped:
        raise typer.Exit(code=3)
    raise typer.Exit(code=0 if summary.complete or summary.limited else 1)


@app.command("import-manual")
def import_manual(ctx: typer.Context) -> None:
    """Ingest replies saved in runs/manual_inbox/ (<run_id>.txt, and <run_id>__repair.txt)."""
    from gauge.runcmd import import_manual as do_import

    cfg = _load(ctx)
    summary = do_import(_engine(cfg), cfg, _load_indicators(cfg), _load_models(cfg))
    typer.echo(
        f"{summary.imported} runs imported, {summary.repairs_imported} repairs imported, "
        f"{summary.skipped} already imported, {summary.failed} failed"
    )
    for problem in summary.problems:
        typer.echo(f"  problem: {problem}", err=True)
    if summary.imported or summary.repairs_imported:
        typer.echo("next: gauge parse")
    raise typer.Exit(code=1 if summary.problems or summary.failed else 0)


@app.command()
def parse(
    ctx: typer.Context,
    repair: bool = typer.Option(
        False, "--repair", help="Make the one repair attempt for runs with invalid companies."
    ),
    mode: RunMode | None = typer.Option(
        None, "--mode", help="Channel for the repair (cli, api, or manual to write prompt files)."
    ),
    yes: bool = typer.Option(False, "--yes", help="Do not ask before real model calls."),
) -> None:
    """Parse raw replies into judgments; report parse-failure rates per model.

    Each company gets a judgment row (ok, or parse_failure with the reason). With --repair a run
    with invalid companies is repeated ONCE with a correction notice; only the invalid companies
    take their values from the repeat.
    """
    from gauge.runcmd import manual_repair_files, stage_parse
    from gauge.runner.api import ApiConfigError
    from gauge.runner.cursor import CursorLaunchError
    from gauge.runner.factory import build_runner

    cfg = _load(ctx)
    indicators, engine = _load_indicators(cfg), _engine(cfg)
    runner = None
    if repair and mode is None:
        raise typer.BadParameter("--repair needs --mode cli, api or manual")
    if repair and mode is RunMode.manual:
        _report(stage_parse(engine, cfg, indicators))
        with session_scope(engine) as session:
            blocks = manual_repair_files(session, cfg)
        if blocks:
            typer.echo(f"\n{len(blocks)} repair prompt(s) written to {cfg.prompts_dir}:\n")
            typer.echo("\n\n".join(blocks))
            typer.echo("\nThen: gauge import-manual, gauge parse")
        else:
            typer.echo("no manual run needs a repair")
        return
    if repair:
        models = _load_models(cfg)
        try:
            runner = build_runner(mode.value, cfg, models)
        except (CursorLaunchError, ApiConfigError) as exc:
            typer.echo(f"cannot start: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        if not yes and not typer.confirm("The repair attempts use real model calls. Start?"):
            raise typer.Exit(code=1)
    _report(
        stage_parse(
            engine,
            cfg,
            indicators,
            runner=runner,
            repair=repair,
            pause_seconds=cfg.runs.pause_seconds,
            log=typer.echo,
        )
    )


class SmokeChannel(StrEnum):
    cli = "cli"
    api = "api"


@app.command()
def smoke(
    ctx: typer.Context,
    channel: SmokeChannel = typer.Option(..., "--channel", help="cli (Cursor) or api (baseline)."),
    model: str = typer.Option(..., "--model", help="Model key from config/models.yaml, e.g. P1."),
    companies: int = typer.Option(2, "--companies", min=1, max=6, help="Companies in the prompt."),
    transport: str | None = typer.Option(
        None, "--transport", help="cli only: argv or stdin (overrides config for this test)."
    ),
    yes: bool = typer.Option(False, "--yes", help="Do not ask before the real call."),
) -> None:
    """ONE real call on a tiny prompt built from SYNTHETIC data, to test a channel before the study.

    Checks that the CLI/API accepts the prompt and answers with parseable JSON. Writes nothing to
    the database; the reply is saved under runs/smoke/.
    """
    from gauge.config import is_placeholder
    from gauge.pipeline import run_all_dry
    from gauge.runner.api import ApiConfigError, api_key, check_model_listed
    from gauge.runner.cursor import CursorLaunchError, model_is_listed
    from gauge.runner.factory import build_runner
    from gauge.runner.smoke import run_smoke, smoke_prompt

    cfg = _load(ctx)
    indicators, models = _load_indicators(cfg), _load_models(cfg)
    spec = next((m for m in models.models if m.key == model), None)
    wanted = "cursor" if channel is SmokeChannel.cli else "api"
    if spec is None or spec.channel != wanted:
        typer.echo(f"{model!r} is not a {wanted}-channel model in config/models.yaml", err=True)
        raise typer.Exit(code=1)
    if is_placeholder(spec.name):
        typer.echo(f"{model}: fill in the exact model name in config/models.yaml first", err=True)
        raise typer.Exit(code=1)
    if transport is not None:
        if transport not in ("argv", "stdin"):
            raise typer.BadParameter("--transport must be argv or stdin")
        models = models.model_copy(
            update={"cursor": models.cursor.model_copy(update={"prompt_transport": transport})}
        )
    try:
        runner = build_runner(channel.value, cfg, models)
        if channel is SmokeChannel.cli:
            listing = runner.list_models()
            if listing is None or not model_is_listed(spec.name, listing):
                typer.echo(f"{spec.name!r} is not in the Cursor CLI model list", err=True)
                raise typer.Exit(code=1)
            typer.echo(
                f"Cursor CLI {runner.executable[0]} {runner.version()}, transport "
                f"{runner.params.prompt_transport}"
            )
        else:
            api_key(spec.provider)
            check_model_listed(spec.provider, spec.name)
    except (CursorLaunchError, ApiConfigError) as exc:
        typer.echo(f"cannot start: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    dry = load_study(DRY_CONFIG)
    if not Path(make_url(dry.database_url()).database).is_file():
        run_all_dry(DRY_CONFIG)
    prompt, codes = smoke_prompt(dry, load_indicators(dry), companies)
    typer.echo(f"prompt: {len(prompt.combined):,} characters, {len(codes)} synthetic companies")
    if not yes and not typer.confirm(f"Make ONE real call to {spec.name} ({wanted} channel)?"):
        raise typer.Exit(code=1)
    try:
        report = run_smoke(
            runner,
            prompt,
            codes,
            indicators.driver_labels,
            model_key=model,
            model_name=spec.name,
            channel=wanted,
            out_dir=cfg.runs_dir / "smoke",
        )
    except CursorLaunchError as exc:
        typer.echo(f"call not made: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"exit code {report.exit_code}, {report.duration_s:.1f} s, reply {report.reply_chars:,} "
        f"characters, JSON found: {report.json_found}, valid companies "
        f"{report.companies_valid}/{report.companies_expected}"
    )
    for problem in report.problems:
        typer.echo(f"  problem: {problem}", err=True)
    typer.echo(f"saved {report.saved_to}")
    typer.echo("SMOKE TEST PASSED" if report.ok else "SMOKE TEST FAILED")
    raise typer.Exit(code=0 if report.ok else 1)


@app.command()
def evaluate(ctx: typer.Context) -> None:
    """Score judgments against the rules (no LLM-as-judge): claims, transitions, flags, metrics.

    Needs the frozen rules, the sample's data and parsed runs. Rebuilds everything it derives; human
    annotations are never deleted.
    """
    from gauge.analysiscmd import stage_evaluate

    cfg = _load(ctx)
    _report(stage_evaluate(_engine(cfg), cfg, _load_indicators(cfg)))


@app.command()
def stats(ctx: typer.Context) -> None:
    """Hypotheses H1-H6 (Holm within families), the rating-shift test and position effects.

    Run `gauge evaluate` first. Exploratory: pilot scale, correlated judgments.
    """
    from gauge.analysiscmd import stage_stats

    cfg = _load(ctx)
    _report(stage_stats(_engine(cfg), cfg, _load_indicators(cfg)))


@app.command()
def checklist(ctx: typer.Context) -> None:
    """Generate docs/REPORTING_CHECKLIST.md (GUIDE-LLM / MI-CLEAR-LLM items) from the run logs."""
    from gauge.analysiscmd import stage_checklist

    cfg = _load(ctx)
    _report(stage_checklist(_engine(cfg), cfg, _load_indicators(cfg), _load_models(cfg)))


@app.command()
def export(ctx: typer.Context) -> None:
    """Export the result tables (CSV) and RESULTS.md to the results folder."""
    from gauge.analysiscmd import stage_export

    cfg = _load(ctx)
    _report(stage_export(_engine(cfg), cfg))


if __name__ == "__main__":  # pragma: no cover
    app()
