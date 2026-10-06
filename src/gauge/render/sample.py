"""Markdown documents that show complete prompts for human review (docs/sample_prompts.md)."""

from __future__ import annotations

from collections.abc import Iterable

from gauge.config import IndicatorsConfig, StudyConfig
from gauge.render.runs import RenderContext, render_condition

FENCE = "~~~~"  # prompts contain Markdown (and could contain ```), so use a rarer fence


def source_banner(ctx: RenderContext) -> str:
    """One honest sentence about where the numbers in a sample prompt come from."""
    ev = ctx.evidence
    if ev.synthetic:
        return (
            "SYNTHETIC DATA: invented numbers from the dry-run generator, shown only to display "
            "the format. They say nothing about any real company."
        )
    if ev.provisional:
        return (
            f"PROVISIONAL REAL DATA: {ev.analysis_fy} values of the {len(ev.companies)} candidate "
            "companies, with masked codes. The final sample is not selected yet "
            "(FY2022-23 and FY2023-24 are not loaded), so codes, cut-points and sector statistics "
            "will change."
        )
    return f"REAL DATA: the selected sample, {ev.analysis_fy}."


def sample_section(
    cfg: StudyConfig,
    indicators: IndicatorsConfig,
    ctx: RenderContext,
    conditions: Iterable[str],
    *,
    heading: str,
) -> str:
    """One `## heading` section with the complete prompt of each condition, companies in code
    order. What is inside a fence is exactly what a Cursor model would receive."""
    parts = [f"## {heading}", "", f"*{source_banner(ctx)}*", ""]
    for condition in conditions:
        prompt = render_condition(cfg, indicators, ctx, condition)
        parts += [
            f"### {condition}",
            "",
            f"{len(prompt.company_order)} companies in code order; {len(prompt.combined):,} "
            f"characters; SHA-256 `{prompt.sha256}`.",
            "",
            FENCE,
            prompt.combined.rstrip("\n"),
            FENCE,
            "",
        ]
    return "\n".join(parts)
