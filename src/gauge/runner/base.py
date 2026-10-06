"""The runner contract shared by the mock, Cursor-CLI, manual and API channels.

A runner receives only prompt text (plus an optional system prompt for the API channel). It never
receives ground truth, rule classes or evaluation results (§0 critical principle).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class RunRequest:
    run_id: str
    model: str  # exact model name from config/models.yaml; never "auto"
    condition: str
    repetition: int
    seed: int
    prompt: str
    system_prompt: str | None = None
    is_repair: bool = False


@dataclass
class RunResult:
    """Everything hard rule 5 requires per run, except the prompt (kept on the request)."""

    stdout: str
    stderr: str
    exit_code: int
    duration_s: float
    command: list[str]
    cli_version: str
    started_utc: datetime
    finished_utc: datetime
    # API-channel extras (temperature, provider_model, request_json, response_json, ...).
    extra: dict[str, Any] = field(default_factory=dict)


class Runner(Protocol):
    mode: str  # one of vocab.RUN_MODES

    def run(self, request: RunRequest) -> RunResult: ...
