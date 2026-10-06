"""Construct the runner for a channel mode and check that it may start (hard rules 1-4, 7, 12)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

import httpx
from sqlalchemy.orm import Session

from gauge.config import (
    ConfigError,
    IndicatorsConfig,
    ModelsConfig,
    StudyConfig,
    assert_models_ready,
)
from gauge.render.runs import RunPrompt
from gauge.rules.freeze import verify_frozen
from gauge.runner.api import ApiConfigError, ApiRunner, api_key, check_model_listed
from gauge.runner.cursor import (
    CursorLaunchError,
    CursorRunner,
    model_is_listed,
    sandbox_entries,
)

CHANNEL_OF_MODE = {"cli": "cursor", "manual": "cursor", "api": "api"}


def specs_for(models: ModelsConfig, mode: str):
    """The enabled models served by a channel mode."""
    return [m for m in models.enabled() if m.channel == CHANNEL_OF_MODE[mode]]


def build_runner(mode: str, cfg: StudyConfig, models: ModelsConfig, **kwargs):
    """The runner for `mode` ("cli" or "api"). Raises CursorLaunchError / ApiConfigError."""
    if mode == "cli":
        return CursorRunner(models.cursor, cfg.sandbox_dir, **kwargs)
    if mode == "api":
        spec = specs_for(models, "api")[0]
        return ApiRunner(spec.provider, models.api, **kwargs)
    raise ValueError(f"no automatic runner for mode {mode!r}")


@dataclass
class Preflight:
    problems: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def preflight(
    session: Session,
    cfg: StudyConfig,
    indicators: IndicatorsConfig,
    models: ModelsConfig,
    mode: str,
    run_prompts: Iterable[RunPrompt],
    *,
    runner=None,
    http_client: httpx.Client | None = None,
) -> Preflight:
    """Everything that must be true before the first call. Each failure is one line of advice."""
    result = Preflight()
    run_prompts = list(run_prompts)

    # rule 7: nothing frozen may have changed, and every prompt must still be the frozen one
    result.problems += verify_frozen(cfg, session, indicators, models)

    specs = specs_for(models, mode)
    if not specs:
        result.problems.append(f"no enabled model uses the {CHANNEL_OF_MODE[mode]} channel")
        return result
    try:  # rule 4: no placeholders, no "auto"
        assert_models_ready(models, roles=sorted({s.role for s in specs}))
    except ConfigError as exc:
        result.problems.append(str(exc).replace("\n  ", "; "))

    if mode == "cli":
        _preflight_cli(result, cfg, specs, run_prompts, runner)
    elif mode == "api":
        _preflight_api(result, specs, http_client)
    return result


def _preflight_cli(result: Preflight, cfg, specs, run_prompts, runner) -> None:
    if runner is None:
        result.problems.append("the Cursor runner could not be created")
        return
    entries = sandbox_entries(cfg.sandbox_dir)
    if entries:  # rule 1
        result.problems.append(f"{cfg.sandbox_dir} must be empty before a run, but holds {entries}")
    result.info.append(f"Cursor CLI: {runner.executable[0]} (version {runner.version()})")

    listing = runner.list_models()  # rule 4: the CLI provides a model list, so use it
    if listing is None:
        result.problems.append(
            "the Cursor CLI's model list could not be read (`--list-models`): "
            "is it installed and logged in?"
        )
    else:
        for spec in specs:
            if not model_is_listed(spec.name, listing):
                result.problems.append(
                    f"{spec.key}: {spec.name!r} is not in the Cursor CLI model list"
                )

    cursor_names = {s.key: s.name for s in specs}
    worst = None
    for rp in run_prompts:
        if rp.planned.model_key not in cursor_names:
            continue
        if worst is None or len(rp.prompt.combined) > len(worst.prompt.combined):
            worst = rp
    if worst is not None:
        try:
            runner.check_fits(worst.planned.model_name, worst.prompt.combined)
        except CursorLaunchError as exc:
            result.problems.append(str(exc))
        else:
            result.info.append(
                f"longest prompt: {len(worst.prompt.combined):,} characters "
                f"({runner.params.prompt_transport})"
            )


def _preflight_api(result: Preflight, specs, http_client) -> None:
    for spec in specs:
        try:
            api_key(spec.provider)
            check_model_listed(spec.provider, spec.name, http_client)
        except ApiConfigError as exc:
            result.problems.append(f"{spec.key}: {exc}")
        else:
            result.info.append(f"{spec.key}: {spec.name} is listed on {spec.provider}")
