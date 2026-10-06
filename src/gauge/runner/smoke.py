"""The smoke test (spec Phase 5): ONE real call per channel on a tiny prompt, run by the owner.

It exists to find out, cheaply and before the 20 real runs, whether the channel works at all: that
the CLI starts with the documented flags, accepts the prompt (argv or stdin), answers with the
requested JSON, and leaves the sandbox empty; or that the API key, model id and parameters are
accepted.

The prompt is built by the real renderer from the SYNTHETIC dry-run data (invented numbers, made-up
sectors), cut to two companies. It touches no study data, writes nothing to the database, and its
reply is saved under runs/smoke/ with a small JSON log.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from gauge.config import IndicatorsConfig, StudyConfig
from gauge.db.session import make_engine, session_scope
from gauge.parse.judgments import validate_response
from gauge.render.prompts import RenderedPrompt
from gauge.render.runs import prepare_render, render_condition, subset_context
from gauge.runner.base import RunRequest, RunResult


@dataclass
class SmokeReport:
    model_key: str
    model_name: str
    channel: str
    prompt_chars: int
    prompt_sha256: str
    exit_code: int
    duration_s: float
    cli_version: str
    reply_chars: int
    json_found: bool
    companies_valid: int
    companies_expected: int
    problems: list[str] = field(default_factory=list)
    saved_to: Path | None = None

    @property
    def ok(self) -> bool:
        return (
            self.exit_code == 0
            and self.json_found
            and self.companies_valid == self.companies_expected
            and not self.problems
        )


def smoke_prompt(dry_cfg: StudyConfig, dry_indicators: IndicatorsConfig, n_companies: int = 2):
    """(RenderedPrompt, company codes) from the synthetic dry-run database, C1, `n_companies`."""
    engine = make_engine(dry_cfg.database_url())
    try:
        with session_scope(engine) as session:
            ctx = prepare_render(session, dry_cfg, dry_indicators, with_trend=False)
    finally:
        engine.dispose()
    codes = sorted(ctx.evidence.companies)[:n_companies]
    sub = subset_context(ctx, codes)
    return render_condition(dry_cfg, dry_indicators, sub, "C1", tuple(codes)), codes


def run_smoke(
    runner,
    prompt: RenderedPrompt,
    codes: list[str],
    driver_labels: list[str],
    *,
    model_key: str,
    model_name: str,
    channel: str,
    out_dir: Path,
) -> SmokeReport:
    """One call through `runner`; judge the reply with the same validator the study uses."""
    text, system = prompt.for_channel(channel)
    request = RunRequest(
        run_id=f"SMOKE_{model_key}",
        model=model_name,
        condition="C1",
        repetition=1,
        seed=0,
        prompt=text,
        system_prompt=system,
    )
    result: RunResult = runner.run(request)
    check = validate_response(result.stdout, codes, driver_labels)
    problems = [f"{r.code}: {r.error}" for r in check.bad]
    if result.exit_code != 0:
        problems.insert(0, f"exit code {result.exit_code}: {result.stderr.strip()[:500]}")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / f"{model_key}_{stamp}.txt"
    raw_path.write_text(result.stdout, encoding="utf-8", newline="")
    report = SmokeReport(
        model_key=model_key,
        model_name=model_name,
        channel=channel,
        prompt_chars=len(text) + len(system or ""),
        prompt_sha256=hashlib.sha256((system or "").encode() + text.encode()).hexdigest(),
        exit_code=result.exit_code,
        duration_s=result.duration_s,
        cli_version=result.cli_version,
        reply_chars=len(result.stdout),
        json_found=check.extraction.items is not None,
        companies_valid=len(check.results) - len(check.bad),
        companies_expected=len(codes),
        problems=problems,
        saved_to=raw_path,
    )
    log = {
        "report": {k: str(v) for k, v in report.__dict__.items()},
        "command": result.command,
        "stderr": result.stderr,
        "extra": {
            k: v for k, v in result.extra.items() if k not in ("request_json", "response_json")
        },
    }
    raw_path.with_suffix(".json").write_text(json.dumps(log, indent=2), encoding="utf-8")
    return report
