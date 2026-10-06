"""Typed loading and validation of config/*.yaml."""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.engine import make_url

from gauge import vocab

DEFAULT_STUDY_FILE = "config/study.yaml"


def project_root() -> Path:
    """Repository root: $GAUGE_ROOT if set, else two levels above `src/gauge`."""
    env = os.environ.get("GAUGE_ROOT")
    return Path(env).resolve() if env else Path(__file__).resolve().parents[2]


class ConfigError(ValueError):
    """Raised when a config file is invalid or not ready for a real run."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ----------------------------------------------------------------------------------------------
# study.yaml
# ----------------------------------------------------------------------------------------------
class SectorCfg(_Strict):
    name: str
    code: str = Field(pattern=r"^[A-Z]{3}$")


class StudyBlock(_Strict):
    name: str
    analysis_fy: str
    trend_fys: list[str]
    companies_per_sector: int = Field(ge=1, le=10)
    sectors: list[SectorCfg] = Field(min_length=1)

    @field_validator("analysis_fy")
    @classmethod
    def _fy_format(cls, v: str) -> str:
        if not vocab.FY_RE.match(v):
            raise ValueError(f"fiscal year must look like FY2024-25, got {v!r}")
        return v

    @model_validator(mode="after")
    def _check(self) -> Self:
        if not all(vocab.FY_RE.match(fy) for fy in self.trend_fys):
            raise ValueError("every trend_fys entry must look like FY2024-25")
        if len(self.trend_fys) != 3 or self.trend_fys[-1] != self.analysis_fy:
            raise ValueError(
                "trend_fys must list 3 fiscal years, oldest first, ending in analysis_fy"
            )
        if self.trend_fys != sorted(self.trend_fys):
            raise ValueError("trend_fys must be in chronological order")
        codes = [s.code for s in self.sectors]
        names = [s.name for s in self.sectors]
        if len(set(codes)) != len(codes) or len(set(names)) != len(names):
            raise ValueError("sector names and codes must be unique")
        return self


class RunsBlock(_Strict):
    conditions: list[str]
    repetitions: int = Field(ge=1)
    master_seed: int
    pause_seconds: float = Field(ge=0)
    rep2_min_gap_minutes: float = Field(ge=0)
    models_file: str

    @field_validator("conditions")
    @classmethod
    def _conditions(cls, v: list[str]) -> list[str]:
        if sorted(v) != sorted(vocab.CONDITIONS):
            raise ValueError(f"conditions must be exactly {list(vocab.CONDITIONS)}, got {v}")
        return v


class DashboardBlock(_Strict):
    """Which views the dashboard offers (default: all, in vocab.DASHBOARD_VIEWS order)."""

    views: list[str] | None = None
    notice: str | None = None  # shown in the sidebar, e.g. to say a deployment is a snapshot

    @field_validator("views")
    @classmethod
    def _views(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        unknown = [name for name in v if name not in vocab.DASHBOARD_VIEWS]
        if unknown or not v or len(set(v)) != len(v):
            raise ValueError(
                f"views must be a non-empty list of distinct names from {list(vocab.DASHBOARD_VIEWS)}"
                f"; got {v}"
            )
        return v


class StatsBlock(_Strict):
    bootstrap_resamples: int = Field(ge=1)
    ci_level: float = Field(gt=0, lt=1)
    alpha: float = Field(gt=0, lt=1)
    holm_within_family: bool


class PathsBlock(_Strict):
    database_url: str
    indicators_file: str
    raw_data_dir: str
    rules_dir: str
    prompts_registry_dir: str
    frozen_manifest: str
    runs_dir: str
    sandbox_dir: str
    results_dir: str = "data/processed/results"  # tables written by `gauge export`
    docs_dir: str = "docs"  # where generated documents (reporting checklist) go


class StudyConfig(_Strict):
    study: StudyBlock
    runs: RunsBlock
    stats: StatsBlock
    paths: PathsBlock
    dashboard: DashboardBlock = Field(default_factory=DashboardBlock)
    root: Path = Field(default_factory=project_root, exclude=True)

    # -- path helpers (all relative to the project root) ----------------------------------------
    def path(self, relative: str) -> Path:
        return self.root / relative

    @property
    def sandbox_dir(self) -> Path:
        return self.path(self.paths.sandbox_dir)

    @property
    def runs_dir(self) -> Path:
        return self.path(self.paths.runs_dir)

    @property
    def results_path(self) -> Path:
        return self.path(self.paths.results_dir)

    @property
    def docs_path(self) -> Path:
        return self.path(self.paths.docs_dir)

    @property
    def raw_dir(self) -> Path:
        return self.runs_dir / "raw"

    @property
    def prompts_dir(self) -> Path:
        return self.runs_dir / "prompts"

    @property
    def manual_inbox_dir(self) -> Path:
        return self.runs_dir / "manual_inbox"

    def database_url(self) -> str:
        """SQLAlchemy URL; a relative SQLite file is anchored at the project root."""
        url = make_url(self.paths.database_url)
        if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
            db = Path(url.database)
            if not db.is_absolute():
                url = url.set(database=(self.root / db).as_posix())
        return url.render_as_string(hide_password=False)

    @property
    def dashboard_views(self) -> list[str]:
        """The views to offer, in display order."""
        wanted = self.dashboard.views
        if wanted is None:
            return list(vocab.DASHBOARD_VIEWS)
        return [v for v in vocab.DASHBOARD_VIEWS if v in wanted]

    @property
    def n_companies(self) -> int:
        return len(self.study.sectors) * self.study.companies_per_sector

    def masked_codes(self) -> list[str]:
        """Masked company codes for the sample, e.g. CEM-01 .. CEM-05, STL-01 .. (hard rule 9)."""
        return [
            f"{sector.code}-{i:02d}"
            for sector in self.study.sectors
            for i in range(1, self.study.companies_per_sector + 1)
        ]


def _read_yaml(path: Path) -> dict:
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a YAML mapping")
    return data


def load_study(path: str | Path | None = None, root: Path | None = None) -> StudyConfig:
    """Load and validate a study config. `path` is relative to the project root unless absolute."""
    root = root or project_root()
    file = Path(path or DEFAULT_STUDY_FILE)
    file = file if file.is_absolute() else root / file
    data = _read_yaml(file)
    try:
        return StudyConfig(**data, root=root)
    except ValueError as exc:
        raise ConfigError(f"invalid study config {file}: {exc}") from exc


# ----------------------------------------------------------------------------------------------
# models.yaml
# ----------------------------------------------------------------------------------------------
def is_placeholder(name: str | None) -> bool:
    """True for an empty name, 'auto', or anything starting with TODO (hard rule 4)."""
    return name is None or bool(vocab.PLACEHOLDER_RE.search(name))


class ModelSpec(_Strict):
    key: str = Field(pattern=r"^[A-Z]\d$")
    role: Literal["primary", "baseline", "sensitivity"]
    channel: Literal["cursor", "api", "mock"]
    vendor: str
    name: str
    provider: str | None = None
    enabled: bool = True
    error_rate: float | None = Field(default=None, ge=0, le=1)  # mock channel only

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.channel == "api" and self.provider not in ("openrouter", "groq"):
            raise ValueError(f"{self.key}: api channel needs provider openrouter or groq")
        if (
            self.channel == "api"
            and self.provider == "openrouter"
            and not self.name.endswith(":free")
        ):
            raise ValueError(f"{self.key}: OpenRouter model id must end in ':free' (hard rule 12)")
        if self.role == "baseline" and self.channel == "cursor":
            raise ValueError(f"{self.key}: the controlled baseline is an API (or mock) model")
        if self.role == "primary" and self.channel == "api":
            raise ValueError(f"{self.key}: the primary panel runs through Cursor (or mock)")
        if self.role == "primary" and _looks_like_claude(self):
            raise ValueError(f"{self.key}: Claude models are excluded from the primary panel (§0)")
        if self.error_rate is not None and self.channel != "mock":
            raise ValueError(f"{self.key}: error_rate is only valid for the mock channel")
        return self

    @property
    def is_placeholder(self) -> bool:
        return is_placeholder(self.name)


def _looks_like_claude(spec: ModelSpec) -> bool:
    text = f"{spec.vendor} {spec.name}".lower()
    return any(marker in text for marker in vocab.CLAUDE_MARKERS)


class FallbackCfg(_Strict):
    provider: str
    name: str


class ApiParams(_Strict):
    temperature: float = 0
    top_p: float | None = None
    max_tokens: int | None = Field(default=None, ge=1)
    seed: int | None = None
    split_batch_by_sector: bool = False
    fallback: FallbackCfg | None = None
    timeout_seconds: float = Field(default=300, gt=0)
    max_retries: int = Field(default=6, ge=0)


class CursorParams(_Strict):
    """How the Cursor CLI is called (docs/RUNNER.md). Only flags documented at cursor.com/docs/cli
    are ever used: -p, --output-format, --mode, --model, --workspace, --list-models, --version."""

    executables: list[str] = ["agent", "cursor-agent"]  # first one found on PATH is used
    mode: Literal["ask", "plan"] = "ask"  # ask = read-only (documented: no edits, no commands)
    output_format: Literal["text"] = "text"
    prompt_transport: Literal["argv", "stdin"] = "argv"  # stdin is NOT documented: verify first
    timeout_seconds: float = Field(default=900, gt=0)
    argv_limit_chars: int = Field(default=30000, ge=1000)  # Windows: 32,767 for a whole command
    shim_argv_limit_chars: int = Field(default=7500, ge=1000)  # .cmd/.bat shims: cmd.exe, 8,191
    extra_args: list[str] = []  # only flags you have verified with `agent --help`


class ModelsConfig(_Strict):
    models: list[ModelSpec]
    api: ApiParams = ApiParams()
    cursor: CursorParams = CursorParams()

    @model_validator(mode="after")
    def _check(self) -> Self:
        keys = [m.key for m in self.models]
        if len(set(keys)) != len(keys):
            raise ValueError("model keys must be unique")
        if len(self.by_role("primary")) != 4:
            raise ValueError("the primary panel must have exactly 4 enabled models (§4.7)")
        if len(self.by_role("baseline")) != 1:
            raise ValueError("exactly 1 enabled controlled-baseline model is required (§4.7)")
        if self.api.temperature != 0:
            raise ValueError("baseline temperature must be 0 (hard rule 12)")
        return self

    def enabled(self) -> list[ModelSpec]:
        return [m for m in self.models if m.enabled]

    def by_role(self, role: str) -> list[ModelSpec]:
        return [m for m in self.enabled() if m.role == role]


def load_models(cfg: StudyConfig) -> ModelsConfig:
    file = cfg.path(cfg.runs.models_file)
    try:
        return ModelsConfig(**_read_yaml(file))
    except ValueError as exc:
        raise ConfigError(f"invalid models config {file}: {exc}") from exc


def assert_models_ready(
    models: ModelsConfig,
    cli_listed: Iterable[str] | None = None,
    *,
    roles: Iterable[str] = ("primary", "baseline"),
) -> None:
    """Refuse to start real runs while a model name is a placeholder or unknown to the CLI.

    `cli_listed` is the set of names printed by the Cursor CLI's model listing, if it has one
    (hard rule 4). Only Cursor-channel models are checked against it.
    """
    listed = set(cli_listed) if cli_listed is not None else None
    problems: list[str] = []
    for spec in models.enabled():
        if spec.role not in roles or spec.channel == "mock":
            continue
        if spec.is_placeholder:
            problems.append(f"{spec.key}: model name {spec.name!r} is a placeholder")
        elif listed is not None and spec.channel == "cursor" and spec.name not in listed:
            problems.append(f"{spec.key}: {spec.name!r} is not in the Cursor CLI model list")
    if problems:
        raise ConfigError("models not ready for a real run:\n  " + "\n  ".join(problems))


# ----------------------------------------------------------------------------------------------
# indicators.yaml
# ----------------------------------------------------------------------------------------------
class IndicatorSpec(_Strict):
    code: str
    label: str
    unit: str
    group: str
    rankable: bool
    brsr_ref: str
    xbrl_element: str


class ReportAttributeSpec(_Strict):
    code: str
    label: str
    values: list[str]
    note: str | None = None


class KpiSpec(_Strict):
    code: str
    label: str
    unit: str
    formula: str
    better: Literal["lower", "higher"]
    core: bool


class Change2y(_Strict):
    enabled: bool


class IndicatorsConfig(_Strict):
    indicators: list[IndicatorSpec]
    report_attributes: list[ReportAttributeSpec]
    kpis: list[KpiSpec]
    change_2y: Change2y
    leave_one_out_groups: dict[str, list[str]]

    @model_validator(mode="after")
    def _check(self) -> Self:
        codes = [i.code for i in self.indicators]
        if len(set(codes)) != len(codes):
            raise ValueError("indicator codes must be unique")
        if any(i.rankable for i in self.indicators):
            raise ValueError("raw indicators must not be rankable (hard rule 10)")
        known = set(codes)
        for group, members in self.leave_one_out_groups.items():
            if not set(members) <= known:
                raise ValueError(f"leave_one_out_groups.{group} references unknown indicators")
        core = [k for k in self.kpis if k.core]
        if len(core) != 3:
            raise ValueError("exactly 3 core KPIs are required (emissions, water, renewables)")
        return self

    @property
    def core_kpis(self) -> list[KpiSpec]:
        return [k for k in self.kpis if k.core]

    @property
    def driver_labels(self) -> list[str]:
        """Names a model may cite in `top_drivers`: indicator and KPI labels as shown in prompts."""
        return [i.label for i in self.indicators] + [k.label for k in self.kpis]


def load_indicators(cfg: StudyConfig) -> IndicatorsConfig:
    file = cfg.path(cfg.paths.indicators_file)
    try:
        return IndicatorsConfig(**_read_yaml(file))
    except ValueError as exc:
        raise ConfigError(f"invalid indicators config {file}: {exc}") from exc
