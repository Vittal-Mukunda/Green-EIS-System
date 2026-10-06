"""The traceability chain: KPI, inputs, normalisation, validation, filing, fingerprint, retrieval,
human verification. The point of the product is the chain behind a number, so it is drawn as one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from gauge.viewdata_ui import fmt_value

from .icons import icon
from .markup import esc

_NAME = re.compile(r"[a-z][a-z_0-9]*")


@dataclass
class Step:
    glyph: str
    title: str
    value: str = ""  # escaped text, large
    unit: str = ""
    text: str = ""  # trusted HTML
    tone: str = ""  # '', warn, muted, info


def chain_html(steps: list[Step]) -> str:
    out = []
    for s in steps:
        value = (
            f'<div class="eis-step-value">{esc(s.value)}<small>{esc(s.unit)}</small></div>'
            if s.value
            else ""
        )
        text = f'<div class="eis-step-text">{s.text}</div>' if s.text else ""
        out.append(
            f'<div class="eis-step"><div class="eis-node {esc(s.tone)}">{icon(s.glyph)}</div>'
            f'<div class="eis-step-body"><div class="eis-step-head"><span class="eis-step-title">{esc(s.title)}</span></div>'
            f"{value}{text}</div></div>"
        )
    return f'<div class="eis-chain">{"".join(out)}</div>'


def formula_words(formula: str, labels: dict[str, str]) -> str:
    """The configured formula with each indicator code replaced by its label."""
    return _NAME.sub(lambda m: labels.get(m.group(0), m.group(0)), formula)


def inputs_table_html(inputs: list[dict]) -> str:
    rows = []
    for i in inputs:
        if not i["present"]:
            rows.append(
                f'<tr><td>{esc(i["label"])}</td><td class="num"><span class="eis-na">not in the filing data</span></td>'
                '<td class="num"></td></tr>'
            )
            continue
        filed = (
            f"{fmt_value(i['as_filed'], i['as_filed_unit'] or '')}"
            if i["as_filed"] is not None
            else '<span class="eis-na">same as stored</span>'
        )
        flagged = (
            f' <span class="eis-badge warn">{esc(", ".join(i["flags"]))}</span>'
            if i["flags"]
            else ""
        )
        rows.append(
            f"<tr><td>{esc(i['label'])}{flagged}</td>"
            f'<td class="num nowrap"><b>{esc(fmt_value(i["value"], i["unit"]))}</b></td>'
            f'<td class="num nowrap">{filed}</td></tr>'
        )
    return (
        '<div class="eis-inputs"><table class="eis-table"><thead><tr><th>Figure</th>'
        '<th class="num">Stored (standard unit)</th><th class="num">As filed</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def trace_steps(trace: dict, company: str, fy: str, labels: dict[str, str]) -> list[Step]:
    """Turn `gauge.viewdata_ui.source_trace` into the chain. Nothing is inferred: a step whose data is
    missing says so."""
    kpi = trace["kpi"]
    report = trace["report"]
    steps = [
        Step(
            "insights",
            f"KPI · {kpi['label']} · {fy}",
            fmt_value(kpi["value"], kpi["unit"]) if kpi["value"] is not None else "not computed",
            "",
            f"{esc(company)}. Computed as <span class='eis-mono'>{esc(formula_words(trace['formula'], labels))}</span>, "
            f"{esc(kpi['better'])} is better.",
        ),
        Step(
            "dataset",
            "Input figures",
            "",
            "",
            inputs_table_html(trace["inputs"]),
            "info",
        ),
    ]
    converted, overrides = trace["converted"], trace["overrides"]
    if not trace["inputs"] or not any(i["present"] for i in trace["inputs"]):
        norm, tone = "No input figure is stored, so there is nothing to normalise.", "muted"
    else:
        norm = (
            f"{converted} of {len(trace['inputs'])} figures were converted from the unit printed in the filing "
            "to the system's standard unit."
            if converted
            else "Every input is stored in the unit the filing used, so no conversion was needed."
        )
        tone = ""
        if overrides:
            norm += " An XBRL unit label was replaced using evidence from the PDF: " + " ".join(
                esc(o) for o in overrides
            )
            tone = "warn"
    steps.append(Step("sync_alt", "Normalisation", "", "", norm, tone))
    if trace["rules"]:
        steps.append(
            Step(
                "rule",
                "Validation",
                "Data check",
                "",
                "This figure fails: "
                + esc(", ".join(trace["rules"]))
                + ". It is shown but not ranked; "
                "it is a figure to verify, not a finding that the company misreported.",
                "warn",
            )
        )
    else:
        steps.append(
            Step(
                "rule",
                "Validation",
                "Passed",
                "",
                "No error-level data-quality rule touches this figure's inputs.",
            )
        )
    if report is None:
        steps.append(
            Step(
                "description",
                "Source filing",
                "none loaded",
                "",
                f"No filing is loaded for {esc(fy)}.",
                "muted",
            )
        )
        return steps
    assurance = {True: "assured", False: "not assured", None: "assurance not stated"}[
        report["assured"]
    ]
    steps.append(
        Step(
            "description",
            "Source filing",
            report["source_file"] or "not recorded",
            "",
            f"Read from {esc(report['entry_method'])}; boundary {esc(report['boundary'] or 'not stated')}; {esc(assurance)}.",
        )
    )
    steps.append(
        Step(
            "fingerprint",
            "SHA-256 fingerprint",
            "",
            "",
            f'<span class="eis-mono">{esc(report["sha256"])}</span>'
            if report["sha256"]
            else "not recorded",
            "" if report["sha256"] else "muted",
        )
    )
    steps.append(
        Step(
            "event",
            "Retrieved",
            report["retrieved_on"] or "not recorded",
            "",
            "The date the filing file was downloaded for this study.",
            "" if report["retrieved_on"] else "muted",
        )
    )
    if trace["of"]:
        done = trace["checked"]
        steps.append(
            Step(
                "verified",
                "Human verification",
                f"{done} of {trace['of']} inputs",
                "",
                "checked against the filing by a person"
                if done
                else "No input has been checked by a person yet.",
                "" if done else "muted",
            )
        )
    return steps
