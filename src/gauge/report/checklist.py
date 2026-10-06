"""`gauge checklist`: map each GUIDE-LLM / MI-CLEAR-LLM minimum reporting item to this study, filled
from the run logs where they can answer it (spec §5).

Statuses: met, partially met, not met, or "not assessable yet" (no runs of that channel). The reason
is written out, including what the access channel does not allow (Cursor's hidden system prompt, no
temperature control).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from gauge.config import ModelsConfig, StudyConfig
from gauge.db.models import Judgment, Model, Run
from gauge.rules.freeze import is_frozen

MET, PARTIAL, NOT_MET, NA = "met", "partially met", "not met", "not assessable yet (no runs)"


@dataclass
class ChecklistItem:
    item: str
    cursor: str
    api: str
    evidence: str


def _runs(session: Session, channels: tuple[str, ...]) -> list[Run]:
    return list(
        session.scalars(
            select(Run)
            .join(Model, Model.id == Run.model_id)
            .where(Model.channel.in_(channels), Run.variant == "")
            .order_by(Run.run_id)
        )
    )


def build_checklist(
    session: Session, cfg: StudyConfig, models: ModelsConfig
) -> list[ChecklistItem]:
    cursor = _runs(session, ("cursor", "mock"))
    api = _runs(session, ("api",))
    both = cursor + api
    names = {m.key: m for m in session.scalars(select(Model))}

    def all_have(runs: list[Run], attr: str) -> bool:
        return bool(runs) and all(getattr(r, attr) not in (None, "") for r in runs)

    def span(runs: list[Run]) -> str:
        dates = [r.started_utc for r in runs if r.started_utc]
        return f"{min(dates):%Y-%m-%d} to {max(dates):%Y-%m-%d}" if dates else "no dates"

    cli_versions = sorted({r.cli_version for r in cursor if r.cli_version})
    provider_models = sorted({r.provider_model for r in api if r.provider_model})
    temps = sorted({r.temperature for r in api if r.temperature is not None})
    n_repairs = sum(r.is_repair for r in both)
    n_failed = sum(r.status != "success" for r in both)
    parsed = session.scalar(select(func.count()).select_from(Judgment)) or 0
    model_list = "; ".join(f"{m.key} = {m.name} ({m.vendor})" for m in names.values() if m.enabled)

    items = [
        ChecklistItem(
            "Model name and identifier",
            PARTIAL if cursor else NA,
            (MET if all_have(api, "provider_model") else PARTIAL) if api else NA,
            f"Names as configured: {model_list}. Cursor exposes the model name only, not the backing "
            "snapshot. API provider-returned model string(s): "
            f"{', '.join(provider_models) or 'none logged'}.",
        ),
        ChecklistItem(
            "Provider and access channel",
            MET if cursor else NA,
            MET if api else NA,
            "Every run row records its mode (cli, manual, api) and the model its channel and provider. "
            "Primary panel through the Cursor agent; baseline through the OpenRouter free tier.",
        ),
        ChecklistItem(
            "Version and date",
            (PARTIAL if all_have(cursor, "cli_version") else NOT_MET) if cursor else NA,
            (MET if all_have(api, "provider_model") and all_have(api, "started_utc") else PARTIAL)
            if api
            else NA,
            f"Cursor: CLI version(s) {', '.join(cli_versions) or 'none logged'} and dates "
            f"{span(cursor)}; the backing model version is not exposed and can change without notice. "
            f"API: dates {span(api)}.",
        ),
        ChecklistItem(
            "System prompt",
            PARTIAL if cursor else NA,
            (MET if all_have(api, "system_prompt_sha256") else NOT_MET) if api else NA,
            "Our instructions are logged in full with their SHA-256 for every run (for the Cursor "
            "channel as the first part of one message). Cursor's own hidden system instructions are "
            "not available, so the Cursor items cannot be fully met.",
        ),
        ChecklistItem(
            "User prompt",
            (MET if all_have(cursor, "prompt_sha256") and is_frozen(cfg) else PARTIAL)
            if cursor
            else NA,
            (MET if all_have(api, "prompt_sha256") and is_frozen(cfg) else PARTIAL) if api else NA,
            "The full prompt text and its SHA-256 are stored per run, the rendered prompt of every "
            "planned run is frozen in registry/frozen_manifest.json, and docs/sample_prompts.md shows "
            "complete examples.",
        ),
        ChecklistItem(
            "Temperature and other parameters",
            NOT_MET if cursor else NA,
            (MET if temps and all_have(api, "request_json") else PARTIAL) if api else NA,
            f"Cursor: the agent exposes no temperature or sampling control, so none was set. API: "
            f"temperature {', '.join(map(str, temps)) or 'not logged'}; top_p, max_tokens and seed are "
            "logged as sent with the full request body.",
        ),
        ChecklistItem(
            "Number of runs",
            MET if cursor else NA,
            MET if api else NA,
            f"{len(both)} runs logged ({len(cursor)} Cursor/mock, {len(api)} API), of which "
            f"{n_repairs} repair attempts and {n_failed} not successful. See run_counts.csv.",
        ),
        ChecklistItem(
            "Parsing and aggregation",
            MET if cursor else NA,
            MET if api else NA,
            f"Strict per-company validation of one JSON array, a single repair attempt, parse-failure "
            f"rates reported per model ({parsed} judgments stored). Aggregation: rule-based scoring, "
            "attribute agreement, Krippendorff's alpha and kappas with company bootstrap, no "
            "LLM-as-judge (docs/METHODS.md).",
        ),
        ChecklistItem(
            "Data-leakage safeguards",
            PARTIAL if cursor else NA,
            PARTIAL if api else NA,
            "Company names are masked in every prompt and checked for leaks; each run is a fresh "
            "session; Cursor runs start in an empty sandbox directory; prompts and rules are frozen "
            "before the first run. Not controllable: whether the models saw the filings or the "
            "companies' figures in training, or what Cursor's agent does beyond the sandbox.",
        ),
    ]
    return items


def render_checklist(items: list[ChecklistItem], *, mock: bool) -> str:
    lines = [
        "# Reporting checklist (GUIDE-LLM / MI-CLEAR-LLM minimum items)",
        "",
        "Generated by `gauge checklist` from the run logs; regenerate after the runs.",
        "",
    ]
    if mock:
        lines += [
            "> **MOCK DATA.** Filled from a dry run's logs; it says nothing about a real study.",
            "",
        ]
    lines += [
        "| Item | Cursor runs (primary panel) | API baseline | Evidence / reason |",
        "| --- | --- | --- | --- |",
    ]
    for it in items:
        lines.append(f"| {it.item} | {it.cursor} | {it.api} | {it.evidence.replace('|', '/')} |")
    lines += [
        "",
        "Limitations to state in the paper: Cursor's agent adds its own hidden system instructions; the "
        "temperature cannot be controlled for the Cursor runs; the backing model versions may change "
        "without notice (mitigation: a fully controlled open-model API baseline, plus this checklist); "
        "companies are batched in each prompt; the study is pilot-scale.",
        "",
    ]
    return "\n".join(lines)


def write_checklist(session: Session, cfg: StudyConfig, models: ModelsConfig) -> Path:
    from gauge.report.tables import uses_mock_runs

    items = build_checklist(session, cfg, models)
    path = cfg.docs_path / "REPORTING_CHECKLIST.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(render_checklist(items, mock=uses_mock_runs(session)).encode("utf-8"))
    return path
