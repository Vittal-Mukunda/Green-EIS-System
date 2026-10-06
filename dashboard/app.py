"""Green EIS dashboard (spec §9). Reads from the database only, never calls a model.

The evidence pages (companies, sectors, metrics, comparison, query, compliance, registers) live in
`eis_pages.py`; the model views are below. It writes two things, both human decisions: an annotation
of a model claim, and a reviewer's check of a stored value against its filing. Run with
`streamlit run dashboard/app.py -- --config config/study.yaml` (the config after `--` selects the
database and the pages; `config/study_dry.yaml` shows the synthetic dry run). A host that cannot
pass arguments sets GAUGE_CONFIG instead (see `streamlit_app.py`).

Each page has its own address: `?page=compare-companies`.

Wording rule (spec §11): outputs are "model output", never what a model "thinks"; the benchmarks are
within-sample and small; an SDG mapping indicates relevance, not achievement.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# A host that only runs `pip install -r requirements.txt` has not installed this project, so put
# `src/` (and this folder, for `eis_pages`) on the path before importing. `gauge.config.project_root()`
# then resolves correctly.
for _path in (Path(__file__).resolve().parents[1] / "src", Path(__file__).resolve().parent):
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pandas as pd
import streamlit as st
from components.app_shell import inject_styles, render_shell
from components.charts import show
from components.page_header import page_header
from eis_pages import EVIDENCE_PAGES, Ctx
from sqlalchemy.engine.url import make_url

from gauge import vocab
from gauge.config import load_indicators, load_study
from gauge.db.session import make_engine, session_scope
from gauge.evaluate.results import load_metrics
from gauge.evaluate.standards import StandardsError, load_standards
from gauge.report.figures import (
    interval_bar,
    rating_shift_figure,
    transition_stack,
)
from gauge.report.tables import (
    agreement_between_models,
    attribute_agreement,
    context_effects,
    parse_failure_table,
    scorecard,
    uses_mock_runs,
)
from gauge.viewdata import (
    AnnotationError,
    annotator_agreement,
    audit_runs,
    claims_to_annotate,
    company_directory,
    data_as_of,
    disagreement_queue,
    evidence_markdown,
    headline_counts,
    judgments_for_company,
    judgments_for_taxonomy,
    run_detail,
    save_annotation,
    search_runs,
)

FOOTER_MODEL = (
    "Pilot-scale, exploratory study. Model outputs are measurements of model behaviour, not evidence "
    "that any company is greener than another; benchmarks come from a small within-sample set."
)
FOOTER_DATA = (
    "Pilot-scale, exploratory study. Metrics are computed from each company's own BRSR "
    "disclosures, which are self-reported; benchmarks come from a small within-sample set, and a "
    "lower intensity does not by itself show that a company is greener."
)


def _config_arg() -> str:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=os.environ.get("GAUGE_CONFIG", "config/study.yaml"))
    args, _ = parser.parse_known_args(sys.argv[1:])
    return args.config


st.set_page_config(
    page_title="Green EIS",
    page_icon=":material/eco:",
    layout="wide",
    initial_sidebar_state="auto",  # open on a laptop, collapsed on a phone
)

cfg = load_study(_config_arg())
indicators = load_indicators(cfg)
PAGES = cfg.dashboard_views
FOOTER = FOOTER_MODEL if any(v in vocab.MODEL_VIEWS for v in PAGES) else FOOTER_DATA
url = make_url(cfg.database_url())
if url.get_backend_name() == "sqlite" and url.database and not Path(url.database).is_file():
    st.warning("Database not found. Run `gauge init-db` first.")  # never create an empty file here
    st.stop()
engine = make_engine(cfg.database_url())

inject_styles(PAGES)
# A page's address picks the page on first load, so a link such as ?page=sectors can be shared.
slugs = {vocab.slug(v): v for v in PAGES}
if st.session_state.get("view") not in PAGES:
    st.session_state["view"] = slugs.get(st.query_params.get("page", ""), PAGES[0])
with session_scope(engine) as _session:
    _directory = company_directory(_session)
    _counts = headline_counts(_session)
    _asof = data_as_of(_session)
page, real_names, _people = render_shell(
    PAGES,
    _directory,
    pilot={
        "companies": _counts["companies"],
        "sectors": _directory["sector"].nunique(),
        "latest_fy": _asof["latest_fy"],
    },
    status={
        "latest_fy": _asof["latest_fy"],
        "retrieved_on": _asof["retrieved_on"],
        "filings": _counts["filings"],
    },
    notice=cfg.dashboard.notice,
)
st.query_params["page"] = vocab.slug(page)


# ---- shared helpers ---------------------------------------------------------------------------------
def banner(session) -> None:
    if uses_mock_runs(session):
        st.warning(
            "MOCK DATA: these runs come from a dry run (synthetic companies, MockRunner). The numbers "
            "exercise the dashboard and say nothing about a real model or company."
        )


def need_evaluation(frame: pd.DataFrame, what: str) -> bool:
    if frame is None or frame.empty:
        st.info(
            f"No {what} yet. Run `gauge run`, `gauge parse`, `gauge evaluate` and `gauge stats`."
        )
        return True
    return False


# ---- 2. scorecard -------------------------------------------------------------------------------------
def page_scorecard() -> None:
    with session_scope(engine) as s:
        banner(s)
        metrics = load_metrics(s)
        card = scorecard(s, metrics)
        if need_evaluation(card, "evaluation results"):
            return
        effects = context_effects(s, metrics)
        msa = attribute_agreement(s, metrics)
        parse = parse_failure_table(s)
    st.markdown("**Per model and condition**")
    primary = card[card["role"] == "primary"]
    baseline = card[card["role"] != "primary"]
    st.markdown("Primary panel")
    st.dataframe(primary, hide_index=True, width="stretch")
    show(interval_bar(primary, "model", "t2_accuracy", "condition", "T2 accuracy against the rule"))
    st.markdown("Controlled baseline (reported alongside, never pooled with the panel)")
    st.dataframe(baseline, hide_index=True, width="stretch")
    st.markdown(
        "**Agreement with the standard and within appraiser** (attribute agreement analysis)"
    )
    st.dataframe(msa, hide_index=True, width="stretch")
    st.markdown("**Context distortion and T3 update consistency**")
    st.dataframe(effects, hide_index=True, width="stretch")
    st.markdown("**Parse-failure rates**")
    st.dataframe(parse, hide_index=True, width="stretch")


# ---- 3. C1 vs C2 ----------------------------------------------------------------------------------------
def page_c1c2() -> None:
    from gauge.evaluate.frame import load_frame

    with session_scope(engine) as s:
        banner(s)
        metrics = load_metrics(s)
        effects = context_effects(s, metrics)
        between = agreement_between_models(metrics)
        frame = load_frame(s)
    if need_evaluation(effects, "C1 vs C2 results"):
        return
    st.markdown(
        "**Rating shift C2 minus C1, per model** (T3 rating, same model, company and repetition)"
    )
    show(rating_shift_figure(frame))
    st.markdown("**Transition consistency** (share of C1 to C2 transitions, by the T3 update rule)")
    show(transition_stack(effects))
    st.markdown(
        "**Agreement between models in each condition** (primary panel, bootstrap 95% intervals)"
    )
    st.dataframe(between, hide_index=True, width="stretch")
    for column in ("t2_alpha_nominal", "t3_alpha_ordinal"):
        if column in between and between[column].notna().any():
            show(interval_bar(between, "condition", column, None, column))


# ---- 4. disagreement queue ---------------------------------------------------------------------------------
def page_queue() -> None:
    with session_scope(engine) as s:
        banner(s)
        queue = disagreement_queue(s)
        if need_evaluation(queue, "disagreement flags"):
            return
        kinds = sorted(queue["type"].unique())
        chosen_kind = st.multiselect("Flag types", kinds, default=kinds)
        shown = queue[queue["type"].isin(chosen_kind)]
        st.dataframe(shown, hide_index=True, width="stretch")
        if shown.empty:
            return
        options = {
            f"{r.type} | {r.company} | {r.condition or '-'} | {r.model or 'all models'} "
            f"| rep {r.repetition}": r
            for r in shown.itertuples()
        }
        pick = options[st.selectbox("Open a flag", list(options))]
        code = pick.company
        st.subheader(f"Evidence and every model's output for {code}")
        try:
            standards = load_standards(s, cfg, indicators)
            rule_class = standards.t2[code].t2_class
            expected = standards.t3[code].expected if code in standards.t3 else "n/a"
            st.caption(
                f"Rule class (T2 standard): {rule_class}. "
                f"The T3 update rule expects the rating to go: {expected}."
            )
        except StandardsError as exc:
            st.caption(f"Standards unavailable: {exc}")
        left, right = st.columns(2)
        for column, condition in ((left, "C1"), (right, "C2")):
            with column:
                st.markdown(f"**Shown under {condition}**")
                try:
                    st.markdown(evidence_markdown(s, cfg, indicators, code, condition))
                except (
                    Exception
                ) as exc:  # evidence needs the full sample; say so instead of failing
                    st.caption(f"Evidence unavailable: {exc}")
        st.markdown("**Model outputs**")
        st.dataframe(judgments_for_company(s, code), hide_index=True, width="stretch")


# ---- 5. annotation -----------------------------------------------------------------------
def page_annotation() -> None:
    st.markdown(
        "Label the claims the rules could not settle, and classify judgments with the four-way error "
        "taxonomy. Two annotators label independently; agreement is reported as Cohen's kappa."
    )
    annotator = st.text_input(
        "Annotator name (use the same name every time)", key="annotator"
    ).strip()
    if not annotator:
        st.info("Enter your name to start.")
        return
    tab_claims, tab_taxonomy, tab_kappa = st.tabs(
        ["Claims", "Error taxonomy", "Annotator agreement"]
    )
    with session_scope(engine) as s:
        banner(s)
        with tab_claims:
            todo = claims_to_annotate(s, annotator)
            st.caption(f"{len(todo)} claims left for {annotator}")
            if todo.empty:
                st.success("Nothing left to label.")
            else:
                row = todo.iloc[0]
                st.markdown(
                    f"**{row['company']}** | {row['model']} | {row['condition']} | automatic label: "
                    f"`{row['automatic_status']}` | indicator: {row['indicator'] or '-'}"
                )
                st.info(row["clause"])
                label = st.radio(
                    "Is the claim supported by the evidence shown to the model?",
                    vocab.CLAIM_SUPPORT_LABELS,
                    key="claim_label",
                )
                note = st.text_input("Note (optional)", key="claim_note")
                if st.button("Save and next", key="save_claim"):
                    try:
                        save_annotation(
                            s,
                            annotator=annotator,
                            kind="claim_support",
                            label=label,
                            claim_id=int(row["claim_id"]),
                            note=note or None,
                        )
                        # st.rerun() raises a control-flow exception, which would skip the commit
                        # that session_scope makes on a normal exit: commit first.
                        s.commit()
                        st.rerun()
                    except AnnotationError as exc:
                        st.error(str(exc))
        with tab_taxonomy:
            try:
                truth = {c: r.t2_class for c, r in load_standards(s, cfg, indicators).t2.items()}
            except StandardsError as exc:
                st.info(f"The rule classes are needed first: {exc}")
                truth = {}
            todo = judgments_for_taxonomy(s, annotator, truth) if truth else pd.DataFrame()
            st.caption(f"{len(todo)} judgments left for {annotator}")
            if todo.empty:
                st.success("Nothing left to classify.")
            else:
                row = todo.iloc[0]
                st.markdown(
                    f"**{row['company']}** | {row['model']} | {row['condition']} rep {row['repetition']} | "
                    f"model class **{row['t2_class']}** vs rule **{row['rule_class']}** | automatic: "
                    f"`{row['automatic_suggestion']}`"
                )
                st.info(row["justification"])
                label = st.radio("Category", vocab.TAXONOMY_LABELS, key="taxonomy_label")
                note = st.text_input("Note (optional)", key="taxonomy_note")
                if st.button("Save and next", key="save_taxonomy"):
                    try:
                        save_annotation(
                            s,
                            annotator=annotator,
                            kind="taxonomy",
                            label=label,
                            judgment_id=int(row["judgment_id"]),
                            note=note or None,
                        )
                        # st.rerun() raises a control-flow exception, which would skip the commit
                        # that session_scope makes on a normal exit: commit first.
                        s.commit()
                        st.rerun()
                    except AnnotationError as exc:
                        st.error(str(exc))
        with tab_kappa:
            for kind in vocab.ANNOTATION_KINDS:
                result = annotator_agreement(s, kind)
                if result["n_both"]:
                    st.write(
                        f"{kind}: annotators {', '.join(result['annotators'])}; {result['n_both']} items "
                        f"labelled by both; agreement {result['agreement']:.2f}; Cohen's kappa "
                        f"{result['kappa']:.2f}"
                    )
                else:
                    st.write(f"{kind}: fewer than two annotators with items in common yet")


# ---- 6. audit trail ----------------------------------------------------------------------
def page_audit() -> None:
    with session_scope(engine) as s:
        banner(s)
        runs = audit_runs(s)
        if runs.empty:
            st.info("No runs logged yet.")
            return
        text = st.text_input("Search every column (run id, model, status, hash, ...)")
        shown = search_runs(runs, text)
        st.caption(f"{len(shown)} of {len(runs)} runs")
        st.dataframe(shown, hide_index=True, width="stretch")
        st.download_button(
            "Export the audit table (CSV)", shown.to_csv(index=False), "audit_trail.csv", "text/csv"
        )
        if shown.empty:
            return
        run_id = st.selectbox("Run detail", list(shown["run_id"]), key="audit_run")
        detail = run_detail(s, run_id)
        st.json(
            {
                k: v
                for k, v in detail.items()
                if k not in ("prompt_text", "system_prompt_text", "stdout", "stderr")
            }
        )
        for name in ("system_prompt_text", "prompt_text", "stdout", "stderr"):
            if detail.get(name):
                with st.expander(name.replace("_", " ")):
                    st.code(detail[name], language="markdown")


MODEL_PAGES = {
    "Model reliability scorecard": page_scorecard,
    "C1 vs C2": page_c1c2,
    "Disagreement queue": page_queue,
    "Annotation": page_annotation,
    "Audit trail": page_audit,
}

ctx = Ctx(cfg=cfg, engine=engine, indicators=indicators, real_names=real_names, pages=PAGES)
try:
    if page in EVIDENCE_PAGES:
        EVIDENCE_PAGES[page](ctx)
    else:
        page_header(page, f"{vocab.VIEW_NOTES.get(page, '')}.", page=page)
        MODEL_PAGES[page]()
finally:
    engine.dispose()
with st.container(key="eis-footer"):
    st.caption(FOOTER)
