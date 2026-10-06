"""Closed vocabularies shared by config validation, the DB schema and the output schema."""

from __future__ import annotations

import re
from typing import Final, Literal

CONDITIONS: Final = ("C1", "C2")
T2_CLASSES: Final = ("Leader", "Average", "Laggard")
T2Class = Literal["Leader", "Average", "Laggard"]

ROLES: Final = ("primary", "baseline", "sensitivity")
CHANNELS: Final = ("cursor", "api", "mock")
RUN_MODES: Final = ("cli", "manual", "api", "mock")
RUN_STATUSES: Final = ("pending", "success", "failed", "usage_limit")
PARSE_STATUSES: Final = ("not_parsed", "ok", "repaired", "parse_failure")

SELECTION_STATUSES: Final = ("candidate", "included", "excluded")
ENTRY_METHODS: Final = ("xbrl", "xbrl_comparative", "manual", "synthetic")
BOUNDARIES: Final = ("standalone", "consolidated")
FLAG_SEVERITIES: Final = ("error", "warning")
RULE_KINDS: Final = ("T2", "T3_UPDATE")
CLAIM_TYPES: Final = ("numeric", "indicator_only")
CLAIM_STATUSES: Final = ("supported", "unsupported", "wrong", "pending_annotation")
TRANSITION_LABELS: Final = ("consistent", "violating", "unconstrained")
EXPECTED_DIRECTIONS: Final = ("up", "down", "none")
ANNOTATION_KINDS: Final = ("claim_support", "taxonomy")
CLAIM_SUPPORT_LABELS: Final = ("supported", "unsupported", "wrong", "not_checkable")
TAXONOMY_LABELS: Final = (
    "objective_error",
    "unsupported_claim",
    "interpretation_difference",
    "legitimate_ambiguity",
)
DISAGREEMENT_FLAG_TYPES: Final = ("t2_models_disagree", "t2_flip", "rule_violation")
PLACEHOLDER_RE: Final = re.compile(r"^\s*(todo|tbd|placeholder|auto)?\s*$|^\s*todo", re.IGNORECASE)

FY_RE: Final = re.compile(r"^FY\d{4}-\d{2}$")
MASKED_CODE_RE: Final = re.compile(r"^[A-Z]{3}-\d{2}$")

# Words that mark a Claude model; the primary panel must exclude them (self-preference control).
CLAUDE_MARKERS: Final = ("claude", "anthropic", "sonnet", "opus", "haiku")

SDG_CAPTION: Final = "mapping indicates relevance, not achievement"

# Dashboard views, in display order. The EIS views read the evidence database only; the model views
# need model runs and show an empty-state message until `gauge run`/`parse`/`evaluate` have run.
# The order is the sidebar's: Overview, Analysis, Assurance, Reference (see dashboard/components/sidebar.py).
EIS_VIEWS: Final = (
    "Home",
    "Sectors",
    "KPI scorecard",
    "Companies",
    "Compare companies",
    "Query and chart",
    "Compliance check",
    "Data quality register",
    "Sources and filings",
    "Data verification",
    "Metrics guide",
    "About",
)
MODEL_VIEWS: Final = (
    "Model reliability scorecard",
    "C1 vs C2",
    "Disagreement queue",
    "Annotation",
    "Audit trail",
)
DASHBOARD_VIEWS: Final = EIS_VIEWS + MODEL_VIEWS

# One line under each page name in the sidebar: what the page is for.
VIEW_NOTES: Final = {
    "Home": "Start here: what this system is and what you can do",
    "Companies": "One company: profile, metrics, what they mean",
    "Sectors": "One sector: what it is and how its companies compare",
    "Metrics guide": "What each metric means, with worked examples",
    "Compare companies": "Put chosen companies side by side",
    "Query and chart": "Ask for the data you want; the chart is drawn for you",
    "KPI scorecard": "Every company, every metric, one colour grid",
    "Compliance check": "What each filing discloses, and whether it is consistent",
    "Data quality register": "Every figure that failed an automatic check",
    "Sources and filings": "Where every number came from",
    "Data verification": "Check a number against its filing and record it",
    "About": "What the system can do, and where it stops",
    "Model reliability scorecard": "How reliably each model reads the evidence",
    "C1 vs C2": "Does extra context change a model's answer?",
    "Disagreement queue": "Where models disagree with each other or the rule",
    "Annotation": "Label model claims and error types",
    "Audit trail": "Every model run, with its prompt and output",
}


def slug(text: str) -> str:
    """A page name as it appears in a web address: 'Compare companies' becomes 'compare-companies'."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
