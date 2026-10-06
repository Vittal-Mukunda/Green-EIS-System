"""Result tables, the exported report, the reporting checklist and the analysis commands."""

from __future__ import annotations

import csv
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from gauge.cli import app
from gauge.config import load_indicators, load_models, load_study
from gauge.db.session import make_engine, session_scope
from gauge.pipeline import run_all_dry
from gauge.render.runs import render_run_prompts
from gauge.report.checklist import MET, NA, NOT_MET, PARTIAL, build_checklist, render_checklist
from gauge.report.export import export_results
from gauge.report.tables import all_tables, to_markdown, uses_mock_runs
from gauge.runner.execute import execute_run
from helpers import CannedRunner, good_reply

cli = CliRunner()
DRY = ["--config", "config/study_dry.yaml"]


@pytest.fixture
def dry(proj):
    run_all_dry(root=proj)
    cfg = load_study("config/study_dry.yaml")
    engine = make_engine(cfg.database_url())
    yield SimpleNamespace(
        cfg=cfg, ind=load_indicators(cfg), models=load_models(cfg), engine=engine, root=proj
    )
    engine.dispose()


# ---- Markdown ------------------------------------------------------------------------------------
def test_markdown_merges_interval_columns_and_formats_numbers():
    df = pd.DataFrame(
        {
            "model": ["P1", "P2"],
            "acc": [0.8333333, np.nan],
            "acc_lo": [0.5, np.nan],
            "acc_hi": [0.95, np.nan],
            "n": [12.0, 8.0],
            "k": [10.0, 8.0],
            "p": [1.1e-16, 0.5],
            "flag": [True, False],
        }
    )
    lines = to_markdown(df).splitlines()
    assert lines[0] == "| model | acc | n | k | p | flag |"
    assert lines[2] == "| P1 | 0.833 [0.500, 0.950] | 12 | 10 | 0.000 | yes |"
    assert lines[3] == "| P2 |  | 8 | 8 | 0.500 | no |"  # a missing value is blank, not "nan"


def test_markdown_escapes_pipes_and_handles_empty_tables():
    assert to_markdown(pd.DataFrame()) == "*(no rows)*"
    out = to_markdown(pd.DataFrame({"text": ["a|b", "line\nbreak"]}))
    assert "a/b" in out and "line break" in out and out.count("|") == 4 * 2


def test_small_values_use_scientific_notation_and_counts_stay_integers():
    out = to_markdown(pd.DataFrame({"p": [0.00001234], "resamples": [2000.0], "n_pairs": [40.0]}))
    assert "1.23e-05" in out and "| 2000 | 40 |" in out


# ---- tables from a finished dry run ---------------------------------------------------------------
def test_every_table_is_built_from_the_stored_rows(dry):
    with session_scope(dry.engine) as s:
        tables = all_tables(s)
        mock = uses_mock_runs(s)
    assert mock
    assert set(tables) == {
        "scorecard", "context_effects", "agreement_between_models", "attribute_agreement",
        "hypotheses", "hypothesis_tests", "baseline_vs_panel", "position_effect", "grounding",
        "parse_failure_rates", "run_counts",
    }  # fmt: skip
    assert len(tables["scorecard"]) == 10 and set(tables["scorecard"]["role"]) == {
        "primary",
        "baseline",
    }
    assert len(tables["context_effects"]) == 5
    assert list(tables["agreement_between_models"]["condition"]) == ["C1", "C2"]
    assert set(tables["hypotheses"]["hypothesis"]) == {"H1", "H2", "H3", "H4", "H5", "H6", "S1"}
    assert tables["hypotheses"]["falsification_condition"].notna().all()
    assert set(tables["hypothesis_tests"]["hypothesis"]) == {
        "H1",
        "H2",
        "H3",
        "H4",
        "H5",
        "H6",
        "S1",
    }
    assert set(tables["baseline_vs_panel"]["baseline_model"]) == {"B1"}
    assert len(tables["parse_failure_rates"]) == 5 and len(tables["run_counts"]) > 0
    card = tables["scorecard"]
    assert (card["t2_accuracy_lo"] <= card["t2_accuracy"]).all()
    assert (card["t2_accuracy"] <= card["t2_accuracy_hi"]).all()


def test_the_scorecard_matches_the_stored_metric_rows(dry):
    from gauge.evaluate.results import load_metrics

    with session_scope(dry.engine) as s:
        card = all_tables(s)["scorecard"]
        stored = {(m.model, m.condition): m for m in load_metrics(s) if m.metric == "t2_accuracy"}
    for row in card.itertuples():
        assert row.t2_accuracy == stored[(row.model, row.condition)].value


# ---- export -----------------------------------------------------------------------------------------
def test_export_writes_csv_tables_and_a_report_with_the_mock_banner(dry):
    folder = dry.cfg.results_path
    assert folder == dry.root / "dry" / "results"
    names = {p.name for p in folder.iterdir()}
    assert "RESULTS.md" in names and "scorecard.csv" in names and "hypothesis_tests.csv" in names
    assert len(names) == 12
    with (folder / "scorecard.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["model"] == "B1" and 0 <= float(rows[0]["t2_accuracy"]) <= 1
    assert "t2_accuracy_lo" in rows[0]  # numbers, not formatted text
    text = (folder / "RESULTS.md").read_bytes().decode("utf-8")
    assert text.startswith("# Results") and "**MOCK DATA.**" in text
    for title in (
        "Model scorecard", "Effect of added context", "Agreement between models",
        "Attribute agreement analysis", "Hypotheses and the outcome", "Primary panel vs controlled baseline",
        "Position effect", "Grounding of numeric claims", "Parse-failure rates", "Runs logged",
    ):  # fmt: skip
        assert f"## {title}" in text
    assert "\r" not in text and "**H5**" in text  # tests are printed one table per hypothesis
    assert "pilot-scale" in text.lower() or "Pilot-scale" in text


def test_the_report_makes_no_interpretive_claims(dry):
    text = (dry.cfg.results_path / "RESULTS.md").read_text(encoding="utf-8").lower()
    for phrase in ("better model", "best model", "greener", "proves", "thinks", "perspective"):
        assert phrase not in text


def test_export_can_be_repeated(dry):
    with session_scope(dry.engine) as s:
        again = export_results(s, dry.cfg)
    assert len(again) == 12


# ---- the reporting checklist -------------------------------------------------------------------------
def test_checklist_from_the_dry_run_marks_the_mock_and_has_every_item(dry):
    text = (dry.cfg.docs_path / "REPORTING_CHECKLIST.md").read_text(encoding="utf-8")
    assert "**MOCK DATA.**" in text
    for item in (
        "Model name and identifier", "Provider and access channel", "Version and date",
        "System prompt", "User prompt", "Temperature and other parameters", "Number of runs",
        "Parsing and aggregation", "Data-leakage safeguards",
    ):  # fmt: skip
        assert f"| {item} |" in text
    assert "25 runs logged" in text and "5 repair attempts" in text
    assert "not assessable yet" in text  # there is no API-channel run in a dry run


def test_checklist_without_any_run_is_all_not_assessable(world):
    with session_scope(world.engine) as s:
        items = build_checklist(s, world.cfg, world.models)
    assert len(items) == 9 and all(i.cursor == NA and i.api == NA for i in items)
    assert "0 runs logged" in next(i for i in items if i.item == "Number of runs").evidence


class ApiLike(CannedRunner):
    mode = "api"

    def run(self, request):
        result = super().run(request)
        result.extra.update(
            provider_model="vendor/model-20260101",
            temperature=0.0,
            top_p=None,
            max_tokens=500,
            api_seed=1,
            request_json={"model": request.model, "temperature": 0.0},
            response_json={"model": "vendor/model-20260101"},
        )
        result.cli_version = "openrouter-chat-completions"
        return result


class CliLike(CannedRunner):
    mode = "cli"


def test_checklist_statuses_follow_what_each_channel_can_log(fw):
    from gauge.render.runs import prepare_render

    with session_scope(fw.engine) as s:
        ctx = prepare_render(s, fw.cfg, fw.ind)
        plan = render_run_prompts(fw.cfg, fw.ind, fw.models, ctx)
    reply = good_reply(fw.codes, fw.ind.driver_labels)
    for runner, channel in ((CliLike(default=reply), "cursor"), (ApiLike(default=reply), "api")):
        with session_scope(fw.engine) as s:
            for rp in (r for r in plan if r.planned.channel == channel):
                prompt, system = rp.prompt.for_channel(channel)
                execute_run(s, fw.cfg, runner, rp.planned, prompt, system_prompt=system)
    with session_scope(fw.engine) as s:
        items = {i.item: i for i in build_checklist(s, fw.cfg, fw.models)}
    assert (
        items["Model name and identifier"].cursor == PARTIAL
        and items["Model name and identifier"].api == MET
    )
    assert (
        items["Provider and access channel"].cursor
        == items["Provider and access channel"].api
        == MET
    )
    assert items["Version and date"].cursor == PARTIAL and items["Version and date"].api == MET
    assert items["System prompt"].cursor == PARTIAL and items["System prompt"].api == MET
    assert items["User prompt"].cursor == MET and items["User prompt"].api == MET  # frozen + logged
    assert items["Temperature and other parameters"].cursor == NOT_MET
    assert items["Temperature and other parameters"].api == MET
    assert "canned-0" in items["Version and date"].evidence
    assert "vendor/model-20260101" in items["Model name and identifier"].evidence
    assert "20 runs logged" in items["Number of runs"].evidence
    text = render_checklist(list(items.values()), mock=False)
    assert "MOCK" not in text and "| Item | Cursor runs (primary panel) | API baseline |" in text


def test_user_prompt_is_only_partially_met_before_the_freeze(fw):
    from gauge.rules.freeze import manifest_path

    with session_scope(fw.engine) as s:
        from gauge.render.runs import prepare_render

        ctx = prepare_render(s, fw.cfg, fw.ind)
        rp = render_run_prompts(fw.cfg, fw.ind, fw.models, ctx)[0]
        prompt, system = rp.prompt.for_channel(rp.planned.channel)
        execute_run(s, fw.cfg, CliLike(default=good_reply(fw.codes)), rp.planned, prompt)
    manifest_path(fw.cfg).unlink()
    with session_scope(fw.engine) as s:
        items = {i.item: i for i in build_checklist(s, fw.cfg, fw.models)}
    assert items["User prompt"].cursor == PARTIAL
    assert sys is not None


# ---- the commands ----------------------------------------------------------------------------------------
def test_the_four_commands_run_on_a_finished_dry_run(dry):
    for command, expected in (
        (["evaluate"], "120 judgments (120 valid)"),
        (["stats"], "H1 supported"),
        (["checklist"], "REPORTING_CHECKLIST.md"),
        (["export"], "12 files"),
    ):
        result = cli.invoke(app, [*DRY, *command])
        assert result.exit_code == 0 and expected in result.output, (command, result.output)


def test_commands_need_a_database_and_parsed_runs(proj):
    for command in ("evaluate", "stats", "checklist", "export"):
        result = cli.invoke(app, [command])
        assert result.exit_code == 1 and "database not found" in result.output


def test_evaluate_and_stats_refuse_without_parsed_judgments(world, ctx):
    for command in ("evaluate", "stats"):
        result = cli.invoke(app, [*DRY, command])
        assert result.exit_code == 1 and "no parsed judgments" in result.output


def test_stats_before_evaluate_says_to_evaluate_first(dry):
    from sqlalchemy import delete

    from gauge.db.models import TransitionResult

    with session_scope(dry.engine) as s:
        s.execute(delete(TransitionResult))
    result = cli.invoke(app, [*DRY, "stats"])
    assert result.exit_code == 1 and "run `gauge evaluate`" in result.output
    assert cli.invoke(app, [*DRY, "evaluate"]).exit_code == 0
    assert cli.invoke(app, [*DRY, "stats"]).exit_code == 0
