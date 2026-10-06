"""Everything needed to render the prompts of a study, and the per-run prompts themselves."""

from __future__ import annotations

import csv
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from sqlalchemy.orm import Session

from gauge.config import IndicatorsConfig, ModelsConfig, StudyConfig
from gauge.render.evidence import Evidence, EvidenceError, load_evidence
from gauge.render.prompts import (
    RenderedPrompt,
    RenderError,
    Templates,
    assert_no_identity_leak,
    identity_strings,
    load_templates,
    render_prompt,
)
from gauge.rules.build import (
    RuleFileError,
    build_t2_rule,
    check_rule_matches_evidence,
    load_t2_rule,
    t2_path,
)
from gauge.rules.t2 import T2Rule
from gauge.runner.plan import PlannedRun, plan_runs


@dataclass(frozen=True)
class RenderContext:
    evidence: Evidence
    rule: T2Rule
    templates: Templates
    identities: list[str]  # real names / symbols / ISINs that must never appear in a prompt


@dataclass(frozen=True)
class RunPrompt:
    planned: PlannedRun
    prompt: RenderedPrompt


def prepare_render(
    session: Session,
    cfg: StudyConfig,
    indicators: IndicatorsConfig,
    *,
    provisional: bool = False,
    with_trend: bool = True,
) -> RenderContext:
    """Load evidence, the T2 rule and the templates, and check they agree.

    Real use reads the rule from `registry/rules/t2_v1.yaml` and refuses a stale file. A provisional
    preview has no rule file yet, so the rule is built in memory from the same candidate data.
    """
    try:
        evidence = load_evidence(
            session, cfg, indicators, provisional=provisional, with_trend=with_trend
        )
    except EvidenceError as exc:
        raise RenderError(str(exc)) from exc
    if provisional:
        rule = build_t2_rule(evidence, cfg, indicators)
    else:
        try:
            rule = load_t2_rule(t2_path(cfg))
        except RuleFileError as exc:
            raise RenderError(str(exc)) from exc
        stale = check_rule_matches_evidence(rule, evidence)
        if stale:
            raise RenderError(
                "the T2 rule file does not match the current benchmarks; "
                "run `gauge build-rules`:\n  " + "\n  ".join(stale)
            )
    return RenderContext(evidence, rule, load_templates(cfg), identity_strings(session))


def subset_context(ctx: RenderContext, codes: Sequence[str]) -> RenderContext:
    """The same evidence, rule and templates restricted to some companies (the smoke test sends a
    prompt of two). Sectors left without a company are dropped from the evidence and the rule."""
    unknown = [c for c in codes if c not in ctx.evidence.companies]
    if unknown:
        raise RenderError(f"unknown company codes {unknown}")
    companies = {c: ctx.evidence.companies[c] for c in codes}
    used = {ce.sector for ce in companies.values()}
    evidence = replace(
        ctx.evidence,
        companies=companies,
        sectors={s: b for s, b in ctx.evidence.sectors.items() if s in used},
    )
    rule = ctx.rule.model_copy(
        update={"cut_points": {s: c for s, c in ctx.rule.cut_points.items() if s in used}}
    )
    return RenderContext(evidence, rule, ctx.templates, ctx.identities)


def render_condition(
    cfg: StudyConfig,
    indicators: IndicatorsConfig,
    ctx: RenderContext,
    condition: str,
    company_order: tuple[str, ...] | None = None,
) -> RenderedPrompt:
    prompt = render_prompt(
        cfg=cfg,
        indicators=indicators,
        evidence=ctx.evidence,
        rule=ctx.rule,
        templates=ctx.templates,
        condition=condition,
        company_order=company_order,
    )
    assert_no_identity_leak(prompt, ctx.identities)
    return prompt


def render_run_prompts(
    cfg: StudyConfig,
    indicators: IndicatorsConfig,
    models: ModelsConfig,
    ctx: RenderContext,
    *,
    include_disabled: bool = False,
    conditions: tuple[str, ...] | None = None,
) -> list[RunPrompt]:
    """One prompt per planned run (model x condition x repetition), each with its own company
    order. The prompt depends only on (condition, order), never on the model's name.
    `conditions` limits the rendering (a C1-only preview has no trend data for C2)."""
    plan = plan_runs(cfg, models, sorted(ctx.evidence.companies), include_disabled=include_disabled)
    plan = [p for p in plan if conditions is None or p.condition in conditions]
    return [
        RunPrompt(p, render_condition(cfg, indicators, ctx, p.condition, p.company_order))
        for p in plan
    ]


INDEX_COLUMNS = (
    "run_id",
    "model_key",
    "condition",
    "repetition",
    "seed",
    "order_index",
    "n_companies",
    "chars",
    "sha256",
)


def write_prompt_files(run_prompts: list[RunPrompt], folder: Path) -> Path:
    """One `<run_id>.md` per run (the text a Cursor model receives; paste it for manual mode) and
    an `index.csv` listing them with their hashes. Always UTF-8 with LF newlines."""
    folder.mkdir(parents=True, exist_ok=True)
    for rp in run_prompts:
        (folder / f"{rp.planned.run_id}.md").write_bytes(rp.prompt.combined.encode("utf-8"))
    index = folder / "index.csv"
    with index.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(INDEX_COLUMNS)
        for rp in run_prompts:
            p = rp.planned
            writer.writerow(
                [
                    p.run_id,
                    p.model_key,
                    p.condition,
                    p.repetition,
                    p.seed,
                    p.order_index,
                    len(rp.prompt.company_order),
                    len(rp.prompt.combined),
                    rp.prompt.sha256,
                ]
            )
    return index
