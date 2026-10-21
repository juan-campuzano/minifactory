"""A workflow that writes workflows: the catalog it reads, the gate it must pass, the review a
person sees, and the draft/enable flow. A scripted LLM stands in for Bedrock."""

import os
from pathlib import Path

import pytest
import yaml

from minifactory import ask, catalog, templates, workspace
from minifactory.cli import main
from minifactory.core import registry
from minifactory.core.engine import Engine
from minifactory.core.models import Job
from minifactory.core.workflow import WorkflowSpec, load_workflow, validate_spec
from minifactory.plugins.builtin.routing.intakes import WorkflowGoalIntake
from minifactory.review import review

registry.load_plugins()

GOOD = """\
name: run-tests-pr
route: {description: run the tests of a repository and open a pull request, intake: repo-task, delivery: fixed}
source: {use: static, with: {jobs: []}}
providers: {scm: {use: github}}
steps:
  - {id: clone, use: scm.clone}
  - {id: test, use: shell.run, with: {cmd: "make test"}}
  - {id: deliver, use: scm.open_pr, with: {branch: factory/x, title: tests}}
"""
BAD = GOOD.replace("shell.run", "shell.exec")  # a step that does not exist


def file_block(text):
    return f"FILE: draft.yaml\n{text}END_FILE"


class WorkflowLLM:
    draft, repair = file_block(GOOD), file_block(GOOD)
    calls: list[str] = []

    prompts: list[str] = []

    def complete(self, system, prompt):
        WorkflowLLM.prompts.append(prompt)
        WorkflowLLM.calls.append("repair" if "TASK: repair" in prompt else "draft")
        return WorkflowLLM.repair if "TASK: repair" in prompt else WorkflowLLM.draft


registry.register("llm", "t.workflow")(type("WorkflowLLMProvider", (WorkflowLLM,), {"__init__": lambda self: None}))


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    root = tmp_path / "ws"
    workspace.init(root)
    templates.copy("create-workflow", root)
    monkeypatch.chdir(root)
    WorkflowLLM.draft = WorkflowLLM.repair = file_block(GOOD)
    WorkflowLLM.calls, WorkflowLLM.prompts = [], []
    return root


def run_creator(root, goal="run the tests and open a pull request when they pass"):
    data = yaml.safe_load((root / "workflows" / "create-workflow.yaml").read_text())
    data["providers"]["llm"] = {"use": "t.workflow"}
    spec = WorkflowSpec.model_validate(data)
    validate_spec(spec)
    job = WorkflowGoalIntake().build(goal, None)
    return Engine(spec, root / ".minifactory" / "runs").run_job(job)


# -- the catalog ------------------------------------------------------------------------------
def test_the_catalog_describes_every_step_and_hides_injected_arguments():
    d = catalog.describe()
    assert "shell.run" in d["steps"] and "agent.edit" in d["steps"] and "workflow.save_draft" in d["steps"]
    cmd = next(p for p in d["steps"]["shell.run"]["params"] if p["name"] == "cmd")
    assert cmd["required"] and cmd["type"] == "string"
    assert d["steps"]["agent.edit"]["needs"] == ["llm"]
    names = {p["name"] for kind in ("scm", "llm") for info in d[kind].values() for p in info["params"]}
    assert not names & {"secrets", "client", "transport", "runner"}
    for kind, group in d.items():  # plugins registered by other tests don't count: ours need a description
        for name, info in group.items():
            reg_kind = "step" if kind == "steps" else kind
            if registry.get(reg_kind, name).__module__.startswith("minifactory"):
                assert info["doc"], f"{kind} {name} has no description"


def test_the_markdown_catalog_carries_the_format_rules_and_the_parameters():
    md = catalog.render_markdown()
    assert "Only the keys below exist" in md and "on_fail: fail" in md
    assert "## shell.run" in md and "cmd: string (required)" in md
    assert "## scm: github" in md


def test_plugins_schema_command_prints_the_catalog(capsys):
    assert main(["plugins", "--schema"]) == 0
    assert "# Steps" in capsys.readouterr().out


# -- review ---------------------------------------------------------------------------------
def test_review_points_at_commands_side_effects_and_spend():
    text = "\n".join(str(f) for f in review(WorkflowSpec.model_validate(yaml.safe_load(GOOD))))
    assert "runs a shell command: 'make test'" in text
    assert "pushes a branch and opens a pull request" in text
    assert "acts on GitHub as you" in text
    bare = WorkflowSpec.model_validate({"name": "t", "source": {"use": "static", "with": {"jobs": []}}, "steps": []})
    assert "no `route:` block" in str(review(bare)[0])


# -- the drafting workflow end to end ------------------------------------------------------
def test_a_valid_draft_is_saved_as_a_draft_and_is_not_routable(ws):
    result = run_creator(ws)
    assert result.outcome == "succeeded", result.reason
    saved = ws / "workflows" / "drafts" / "run-tests-pr.yaml"
    assert saved.is_file() and result.artifacts[0].kind == "workflow_draft"
    assert any("runs a shell command" in n for n in result.notes)  # the review travels with the result
    assert WorkflowLLM.calls == ["draft"]  # valid first time: no repair call
    routable = ask.discover(workspace.find(ws).workflow_dirs)  # drafts are invisible to `ask` until enabled
    assert "create-workflow" in routable and "run-tests-pr" not in routable


def test_an_invalid_draft_goes_back_through_the_repair_loop(ws):
    WorkflowLLM.draft = file_block(BAD)
    result = run_creator(ws)
    assert result.outcome == "succeeded", result.reason
    assert {s.id: s.status for s in result.steps}["validate"] == "failed"
    assert WorkflowLLM.calls == ["draft", "repair"]
    assert "shell.run" in (ws / "workflows" / "drafts" / "run-tests-pr.yaml").read_text()


def test_a_draft_that_never_validates_fails_instead_of_saving(ws):
    WorkflowLLM.draft = WorkflowLLM.repair = file_block(BAD)
    result = run_creator(ws)
    assert result.outcome == "failed" and "repair" in result.reason
    assert not (ws / "workflows" / "drafts").exists()


def test_when_the_goal_needs_a_missing_step_the_agent_says_so(ws):
    WorkflowLLM.draft = "MISSING: a step that sends Slack messages"
    result = run_creator(ws)
    assert result.outcome == "failed" and "MISSING: a step that sends Slack messages" in result.reason


def test_an_existing_draft_is_never_overwritten(ws):
    assert run_creator(ws).outcome == "succeeded"
    again = run_creator(ws, goal="the same goal but phrased differently so it is a new job")
    assert again.outcome == "failed" and "already exists" in again.reason


def test_the_draft_is_checked_by_the_same_validator_as_any_workflow(ws):
    run_creator(ws)
    load_workflow(ws / "workflows" / "drafts" / "run-tests-pr.yaml")


def test_the_goal_intake_needs_a_real_sentence_and_makes_a_safe_job():
    with pytest.raises(ValueError, match="at least a sentence"):
        WorkflowGoalIntake().build("do it", None)
    job = WorkflowGoalIntake().build("run the tests, then open a pull request", None)
    assert isinstance(job, Job) and "/" not in job.id and job.attrs["goal"].startswith("run the tests")


# -- enabling --------------------------------------------------------------------------------
def test_enable_moves_a_reviewed_draft_into_the_active_workflows(ws, capsys):
    run_creator(ws)
    assert main(["workflows", "enable", "run-tests-pr", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "runs a shell command" in out and "enabled:" in out
    assert (ws / "workflows" / "run-tests-pr.yaml").is_file()
    assert not (ws / "workflows" / "drafts" / "run-tests-pr.yaml").exists()
    assert "run-tests-pr" in ask.discover(workspace.find(ws).workflow_dirs)


def test_enable_without_confirmation_changes_nothing(ws, capsys):
    run_creator(ws)
    assert main(["workflows", "enable", "run-tests-pr"]) == 2  # no terminal under pytest, no --yes
    assert (ws / "workflows" / "drafts" / "run-tests-pr.yaml").is_file()


def test_enable_errors_are_clear(ws, capsys):
    assert main(["workflows", "enable", "nope", "--yes"]) == 2
    assert "no draft named 'nope'" in capsys.readouterr().err
    run_creator(ws)
    (ws / "workflows" / "run-tests-pr.yaml").write_text("name: x\n")
    assert main(["workflows", "enable", "run-tests-pr", "--yes"]) == 2
    assert "already exists" in capsys.readouterr().err


def test_workflows_list_shows_drafts_separately(ws, capsys):
    run_creator(ws)
    main(["workflows", "list"])
    out = capsys.readouterr().out
    assert "drafts (not routable until" in out and "run-tests-pr" in out


def test_the_create_workflow_template_is_valid_and_delivers_to_its_own_target():
    spec = load_workflow(Path(templates.TEMPLATES_DIR) / "create-workflow" / "workflow.yaml")
    assert spec.route.delivery == "fixed" and spec.route.intake == "workflow-goal"
    assert [s.id for s in spec.steps] == ["init", "catalog", "draft", "validate", "repair", "save"]
    assert os.fspath(Path(templates.TEMPLATES_DIR)).endswith("templates")


def test_a_refusal_is_reported_by_its_conclusion_not_its_preamble():
    from minifactory.plugins.builtin.steps.existing import _what_it_said

    long = "I need to analyze this. " * 40 + "In conclusion no step can post to Slack."
    assert _what_it_said("some analysis\nMISSING: a Slack step\nmore") == "MISSING: a Slack step"
    assert _what_it_said(long).endswith("no step can post to Slack.") and len(_what_it_said(long)) < 320


def test_the_catalog_lists_the_installed_stacks_so_the_agent_does_not_ask_for_one_per_language():
    md = catalog.render_markdown()
    assert "# Stacks installed" in md and "No new step is needed per language" in md
    assert all(f"- {name}:" in md for name in ("python", "node", "java", "flutter"))


def test_the_agent_gets_an_example_of_each_kind_of_workflow(ws):
    result = run_creator(ws)
    work = ws / ".minifactory" / "runs" / "create-workflow" / result.job_id / "work" / "repo"
    assert (work / "EXAMPLE_app-factory.yaml").is_file() and (work / "EXAMPLE_fix-bug.yaml").is_file()
    assert (work / "EXAMPLE.yaml").read_text() == (work / "EXAMPLE_app-factory.yaml").read_text()
    assert "stack.scaffold" in (work / "EXAMPLE_app-factory.yaml").read_text()


def test_the_draft_instruction_says_steps_combine_and_missing_is_a_last_resort(ws):
    run_creator(ws)
    assert any("Steps COMBINE" in p and "agent.plan_app" in p and "never a step" in p for p in WorkflowLLM.prompts)


def test_the_catalog_step_reports_which_version_it_saw(ws):
    import minifactory

    result = run_creator(ws)
    message = next(s.message for s in result.steps if s.id == "catalog")
    assert f"minifactory {minifactory.__version__}" in message and "steps" in message and "stacks" in message


def test_review_flags_a_step_that_only_prints_text_as_a_probable_placeholder():
    spec = WorkflowSpec.model_validate({
        "name": "t", "source": {"use": "static", "with": {"jobs": []}},
        "steps": [{"id": "announce", "use": "shell.run", "with": {"cmd": "echo 'posted to Slack'"}},
                  {"id": "real", "use": "shell.run", "with": {"cmd": "make test"}}]})
    text = "\n".join(str(f) for f in review(spec))
    assert "step 'announce' only prints text" in text and "step 'real' only prints text" not in text


def test_the_draft_instruction_forbids_faking_a_capability(ws):
    run_creator(ws)
    assert any("Never fake one" in p and "echo, printf, true" in p for p in WorkflowLLM.prompts)
