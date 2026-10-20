"""The Flutter app factory end to end (fake flutter + fixture LLM), plus its building blocks."""

import json
from pathlib import Path

import pytest

from minifactory import templates, workspace
from minifactory.core import registry
from minifactory.core.engine import Engine
from minifactory.core.workflow import load_workflow
from minifactory.plugins.builtin import fake_flutter
from minifactory.plugins.builtin.util import collect_files

registry.load_plugins()


@pytest.fixture()
def engine(tmp_path, monkeypatch):
    workspace_root = tmp_path / "ws"  # a workspace made from the packaged template, like a user's
    workspace.init(workspace_root)
    templates.copy("flutter-app-factory", workspace_root)
    monkeypatch.chdir(workspace_root)  # specs/ and fixtures/ are relative to the workspace root
    spec = load_workflow(workspace_root / "workflows" / "flutter-app-factory.yaml")
    spec.providers["scm"].with_ = {"remotes_dir": str(tmp_path / "remote"),
                                   "prs_dir": str(tmp_path / "prs")}
    return Engine(spec, tmp_path / "runs")


def test_every_path(engine):
    jobs = engine.source.jobs()
    results = {r.job_id: r for r in engine.executor.run(jobs, engine.run_job)}
    assert {k: v.outcome for k, v in results.items()} == {
        "todo_app": "succeeded",
        "counter_needs_repair": "succeeded",
        "notes_low_coverage": "succeeded",
        "bad_spec": "failed",
    }

    def status(job: str) -> dict[str, str]:
        return {s.id: s.status for s in results[job].steps}

    assert status("todo_app")["repair"] == "skipped"
    assert status("counter_needs_repair")["analyze"] == "failed"
    assert status("counter_needs_repair")["repair"] == "ok"
    assert results["bad_spec"].reason.startswith("plan: invalid plan")
    assert "implement" not in status("bad_spec")
    # a coverage miss never blocks the PR, it annotates it
    assert any("coverage" in n for n in results["notes_low_coverage"].notes)
    assert results["todo_app"].notes == []


def test_second_run_is_deduplicated(engine):
    jobs = [j for j in engine.source.jobs() if j.name == "todo_app"]
    assert engine.run_job(jobs[0]).outcome == "succeeded"
    again = engine.run_job(jobs[0])
    assert again.outcome == "discarded" and "already exists" in again.reason


def test_fake_flutter_flags_removed_api(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fake_flutter.create(tmp_path, "demo")
    assert fake_flutter.analyze(tmp_path) == 0
    (tmp_path / "lib" / "main.dart").write_text("import 'package:flutter/material.dart';\nFlatButton b;\n")
    assert fake_flutter.analyze(tmp_path) == 1


def test_collect_files_respects_budget_and_stays_inside_repo(tmp_path):
    (tmp_path / "lib").mkdir()
    for name in ("a", "b", "c"):
        (tmp_path / "lib" / f"{name}.dart").write_text("x" * 100)
    assert collect_files(tmp_path, [], ["lib/*.dart"], max_chars=250) == ["lib/a.dart", "lib/b.dart"]
    assert collect_files(tmp_path, ["lib/c.dart"], ["lib/*.dart"]) == [
        "lib/c.dart", "lib/a.dart", "lib/b.dart"]
    with pytest.raises(ValueError, match="inside the repository"):
        collect_files(tmp_path, [], ["../*"])


def test_plan_parsing_tolerates_prose_around_json():
    from minifactory.plugins.builtin.steps_agent import _first_json_object

    reply = 'Sure! Here you go:\n```json\n{"features": [{"id": "a"}]}\n```\nHope it helps {not json}'
    assert _first_json_object(reply) == {"features": [{"id": "a"}]}
    with pytest.raises(ValueError, match="no JSON"):
        _first_json_object("I cannot plan this app.")


def test_parse_edits_strips_one_enclosing_code_fence():
    from minifactory.plugins.builtin.util import parse_edits

    reply = "FILE: lib/a.dart\n```dart\nvoid main() {}\n```\nEND_FILE\nFILE: b.txt\nplain\nEND_FILE"
    assert parse_edits(reply) == {"lib/a.dart": "void main() {}", "b.txt": "plain"}


def test_flutter_defaults_to_the_real_sdk_and_never_silently_falls_back_to_the_fake(monkeypatch, tmp_path):
    from minifactory.plugins.builtin import flutter_tool

    monkeypatch.delenv("FACTORY_FLUTTER", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))  # no flutter anywhere
    with pytest.raises(FileNotFoundError, match="not on PATH"):
        flutter_tool.command()
    assert flutter_tool.command("fake")[-1] == "minifactory.plugins.builtin.fake_flutter"
    monkeypatch.setenv("FACTORY_FLUTTER", "fake")
    assert flutter_tool.command()[-1] == "minifactory.plugins.builtin.fake_flutter"
    with pytest.raises(ValueError, match="unknown flutter tool"):
        flutter_tool.command("nope")


def test_flutter_step_without_the_sdk_fails_with_a_clear_message(monkeypatch, tmp_path):
    from minifactory.core.context import StepContext
    from minifactory.core.models import Job
    from minifactory.plugins.builtin.steps_flutter import FlutterAnalyze

    monkeypatch.delenv("FACTORY_FLUTTER", raising=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr("shutil.which", lambda name: None)
    ctx = StepContext(job=Job(id="a", name="a"), work_dir=tmp_path, scm=None, llm=None, secrets=None,
                      emit=lambda *a, **k: None)
    ctx.repo_dir.mkdir()
    result = FlutterAnalyze().run(ctx, FlutterAnalyze.Params())
    assert result.status == "failed" and "flutter" in result.message


# -- plan size: "una app minima" must not become eight features --------------------------------
class SeqLLM:
    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    def complete(self, system, prompt):
        self.prompts.append(prompt)
        return self.replies.pop(0)


def plan_of(n):
    return json.dumps({"features": [{"id": f"f{i}", "title": "t", "files": ["lib/a.dart"]} for i in range(n)]})


def run_plan(llm, **attrs):
    from minifactory.core.context import StepContext
    from minifactory.core.models import Job
    from minifactory.plugins.builtin.steps_agent import PlanApp

    ctx = StepContext(job=Job(id="a", name="a", attrs={"description": "d", **attrs}), work_dir=Path("."),
                      scm=None, llm=llm, secrets=None, emit=lambda *a, **k: None)
    return PlanApp().run(ctx, PlanApp.Params())


def test_minimal_apps_are_planned_with_at_most_two_features():
    llm = SeqLLM(plan_of(2))
    result = run_plan(llm, size="minimal")
    assert result.status == "ok" and result.outputs["size"] == "minimal"
    assert "SIZE: minimal" in llm.prompts[0] and "AT MOST 2" in llm.prompts[0]


def test_an_oversized_plan_gets_one_retry_with_the_limit_spelled_out():
    llm = SeqLLM(plan_of(5), plan_of(1))
    result = run_plan(llm, size="minimal")
    assert result.status == "ok" and len(result.outputs["features"]) == 1
    assert "had 5 features" in llm.prompts[1] and "limit for a minimal app is 2" in llm.prompts[1]


def test_a_plan_that_stays_oversized_fails_instead_of_overbuilding():
    result = run_plan(SeqLLM(plan_of(5), plan_of(4)), size="minimal")
    assert result.status == "failed" and "over the minimal budget of 2" in result.message


def test_unknown_or_missing_size_means_standard():
    assert run_plan(SeqLLM(plan_of(5))).outputs["size"] == "standard"
    assert run_plan(SeqLLM(plan_of(5)), size="gigantic").outputs["size"] == "standard"
    assert run_plan(SeqLLM(plan_of(6), plan_of(6))).status == "failed"  # standard budget is 5
