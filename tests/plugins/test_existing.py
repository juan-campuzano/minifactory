"""Changing a repository that already exists: locate -> reproduce -> fix -> gates -> PR.
A toy python repo and a scripted LLM stand in for a Flutter repo and Bedrock."""

import json
from pathlib import Path

import pytest

from minifactory.cli import commands as cli
from minifactory.core import registry
from minifactory.core.engine import Engine
from minifactory.core.workflow import WorkflowSpec, validate_spec
from minifactory.plugins.builtin.providers.github import GitHub
from minifactory.plugins.builtin.routing.intakes import REPO_TASK_SYSTEM, RepoTaskIntake, repo_task_job
from minifactory.plugins.builtin.support.git import git

registry.load_plugins()

BUG = "add(2, 3) returns -1 instead of 5"
CALC_BUGGY = "def add(a, b):\n    return a - b\n"
PASSING_TEST = ("import unittest\nfrom calc import add\n\n\nclass T(unittest.TestCase):\n"
                "    def test_zero(self):\n        self.assertEqual(add(0, 0), 0)\n\n\nif __name__ == '__main__':\n"
                "    unittest.main()\n")


def patch(path, search, replace):
    return f"PATCH: {path}\n<<<<<<< SEARCH\n{search}\n=======\n{replace}\n>>>>>>> REPLACE\nEND_PATCH"


FAILING_TEST = PASSING_TEST.replace("add(0, 0), 0", "add(2, 3), 5").replace("test_zero", "test_bug")
REPRO = patch("tests/test_repro.py", "", FAILING_TEST)
CORRECT_FIX = patch("calc.py", "    return a - b", "    return a + b")


class BugLLM:
    """Replies by task. Behaviours are class attributes so each test can break one step."""

    locate = {"files": ["calc.py", "ghost.py"]}
    repro = REPRO
    fix = CORRECT_FIX

    def complete(self, system, prompt):
        if system == REPO_TASK_SYSTEM:
            return json.dumps({"repo": "acme/calc", "task": BUG})
        if "TASK: locate" in prompt:
            return json.dumps(self.locate)
        if "Write ONE new" in prompt:
            return self.repro
        return self.fix


registry.register("llm", "t.bug")(type("BugLLMProvider", (BugLLM,), {"__init__": lambda self: None}))

TESTS = "${env.python} -B -m unittest discover -s tests"  # -B: no stale .pyc when a fix keeps the file size
WORKFLOW = """
name: bugfix
route: {description: fix a bug in an existing python repo, intake: repo-task, delivery: fixed}
vars: {max_lines: 300}
source: {use: static, with: {jobs: []}}
providers:
  scm: {use: local-git, with: {remotes_dir: REMOTES, prs_dir: PRS}}
  llm: {use: t.bug}
steps:
  - {id: guard, use: scm.guard_no_open_pr, with: {branch: "${job.branch}"}}
  - {id: clone, use: scm.clone}
  - {id: baseline, use: shell.run, with: {cmd: "TESTS"}, on_fail: discard}
  - {id: locate, use: agent.locate_files, with: {task: "${job.task}", globs: ["*.py"]}}
  - id: repro
    use: agent.edit
    with:
      instruction: "Write ONE new test. BUG: ${job.task}"
      files: "${steps.locate.outputs.files}"
      allowed_prefixes: ["tests/"]
  - id: repro_fails
    use: shell.run
    with: {cmd: "${env.python} -B -m unittest tests/test_repro.py", expect_failure: true}
    on_fail: discard
  - id: fix
    use: agent.edit
    with:
      instruction: "Fix it. BUG: ${job.task}"
      files: "${steps.locate.outputs.files}"
      extra_files: ["tests/test_repro.py"]
      extra: "${steps.repro_fails.outputs.output}"
  - {id: verify, use: shell.run, with: {cmd: "TESTS"}}
  - {id: size, use: scm.diff_limit, with: {max_files: 5, max_lines: "${vars.max_lines}"}}
  - {id: deliver, use: scm.open_pr, with: {branch: "${job.branch}", title: "fix", body: "${job.task}"}}
"""


@pytest.fixture()
def world(tmp_path, monkeypatch):
    """A bare 'remote' acme/calc with one buggy module and one passing test; returns a runner."""
    work = tmp_path / "seed"
    (work / "tests").mkdir(parents=True)
    (work / "calc.py").write_text(CALC_BUGGY)
    (work / "tests" / "test_ok.py").write_text(PASSING_TEST)
    git("init", "--quiet", "-b", "main", cwd=work)
    git("add", "-A", cwd=work)
    git("-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "initial", cwd=work)
    remote = tmp_path / "remotes" / "acme" / "calc.git"
    remote.parent.mkdir(parents=True)
    git("clone", "--quiet", "--bare", str(work), str(remote))
    BugLLM.locate, BugLLM.repro, BugLLM.fix = {"files": ["calc.py", "ghost.py"]}, REPRO, CORRECT_FIX

    def run(max_lines=300):
        text = WORKFLOW.replace("REMOTES", str(tmp_path / "remotes")).replace("PRS", str(tmp_path / "prs"))
        text = text.replace("TESTS", TESTS).replace("max_lines: 300", f"max_lines: {max_lines}")
        import yaml

        spec = WorkflowSpec.model_validate(yaml.safe_load(text))
        validate_spec(spec)
        engine = Engine(spec, tmp_path / "runs")
        return engine.run_job(repo_task_job("acme/calc", BUG)), remote, tmp_path

    return run


def statuses(result):
    return {s.id: s.status for s in result.steps}


def test_a_bug_is_reproduced_then_fixed_and_delivered_on_a_branch(world):
    result, remote, tmp = world()
    assert result.outcome == "succeeded", result.reason
    assert statuses(result)["repro_fails"] == "ok" and statuses(result)["verify"] == "ok"
    branch = next(json.loads(p.read_text())["branch"] for p in (tmp / "prs" / "acme" / "calc").glob("*.json"))
    assert branch.startswith("factory/fix-")
    fixed = git("--git-dir", str(remote), "show", f"{branch}:calc.py")
    assert "a + b" in fixed
    assert "test_bug" in git("--git-dir", str(remote), "show", f"{branch}:tests/test_repro.py")
    assert "a - b" in git("--git-dir", str(remote), "show", "main:calc.py")  # the default branch is untouched


def test_locate_only_keeps_files_that_really_exist(world):
    result, *_ = world()
    assert next(s for s in result.steps if s.id == "locate").outputs["files"] == ["calc.py"]


def test_a_bug_that_cannot_be_reproduced_changes_nothing(world):
    BugLLM.repro = patch("tests/test_repro.py", "", PASSING_TEST)  # a test that passes proves nothing
    result, remote, tmp = world()
    assert result.outcome == "discarded" and "repro_fails" in result.reason
    assert "expect" in result.reason and not list((tmp / "prs").glob("**/*.json"))
    assert git("--git-dir", str(remote), "branch", "--list", "factory/*") == ""


def test_the_repro_step_cannot_edit_production_code(world):
    BugLLM.repro = patch("calc.py", "    return a - b", "    return 0")
    result, *_ = world()
    assert result.outcome == "failed" and "outside the allowed paths" in result.reason


def test_a_fix_that_does_not_apply_fails_instead_of_clobbering(world):
    BugLLM.fix = patch("calc.py", "    return a * b", "    return a + b")  # search text is not in the file
    result, *_ = world()
    assert result.outcome == "failed" and "found 0 times" in result.reason


def test_an_oversized_change_is_stopped_before_delivery(world):
    result, _, tmp = world(max_lines=1)
    assert result.outcome == "failed" and "change too large" in result.reason
    assert not list((tmp / "prs").glob("**/*.json"))


def test_locate_fails_when_nothing_selected_exists(world):
    BugLLM.locate = {"files": ["ghost.py"]}
    result, *_ = world()
    assert result.outcome == "failed" and "did not select any file" in result.reason


# -- expect_failure ----------------------------------------------------------------------------
def run_shell_step(cmd, tmp_path, **kw):
    from minifactory.core.context import StepContext
    from minifactory.core.models import Job
    from minifactory.plugins.builtin.steps.shell import ShellRun

    ctx = StepContext(job=Job(id="j", name="j"), work_dir=tmp_path, scm=None, llm=None, secrets=None,
                      emit=lambda *a, **k: None)
    ctx.repo_dir.mkdir(exist_ok=True)
    return ShellRun().run(ctx, ShellRun.Params(cmd=cmd, **kw))


def test_expect_failure_accepts_a_red_command_only(tmp_path):
    assert run_shell_step("exit 3", tmp_path, expect_failure=True).status == "ok"
    assert run_shell_step("true", tmp_path, expect_failure=True).status == "failed"
    missing = run_shell_step("definitely_not_a_command_xyz", tmp_path, expect_failure=True)
    assert missing.status == "failed" and "could not run" in missing.message  # 127 never counts as "red"


# -- the intake and the ask flow ----------------------------------------------------------------
def test_repo_task_intake_builds_a_safe_job():
    job = RepoTaskIntake().build("fix in acme/calc: add(2,3) gives -1", BugLLM())
    assert job.name == "acme/calc" and "/" not in job.id and job.attrs["branch"].startswith("factory/fix-")
    assert job.attrs["task"] == BUG


@pytest.mark.parametrize("request_text", ["fix the bug in the sum", "fix the sum in some/other repo"])
def test_repo_task_intake_needs_a_repo_the_user_actually_wrote(request_text):
    with pytest.raises(ValueError, match="owner/name|does not appear"):
        RepoTaskIntake().build(request_text, BugLLM())


def test_ask_with_a_fixed_delivery_workflow_runs_without_choosing_an_output(world, tmp_path, capsys):
    wf_dir = tmp_path / "wf"
    wf_dir.mkdir()
    text = WORKFLOW.replace("REMOTES", str(tmp_path / "remotes")).replace("PRS", str(tmp_path / "prs"))
    text = text.replace("TESTS", TESTS).replace("max_lines: 300", "max_lines: 300")
    route = "route: {description: fix a bug in an existing python repo,"
    (wf_dir / "bugfix.yaml").write_text(text.replace(route, route + " needs: owner/name,"))
    args = ["ask", "fix the bug in acme/calc: add(2, 3) returns -1", "--workflows-dir", str(wf_dir),
            "--router", "keyword", "--threshold", "0.1", "--runs-dir", str(tmp_path / "runs"), "--plain"]
    assert cli.main([*args, "--output", "local", "--yes"]) == 2  # --output makes no sense here
    assert "does not apply" in capsys.readouterr().err
    assert cli.main([*args, "--yes"]) == 0
    assert list((tmp_path / "prs" / "acme" / "calc").glob("*.json"))


# -- github addressing ---------------------------------------------------------------------------
def test_github_addresses_existing_repos_as_owner_name():
    gh = GitHub(owner="me", runner=lambda argv, cwd: (0, "", ""))
    assert gh._full("acme/calc") == "acme/calc" and gh._full("new") == "me/new"
    assert gh.target("acme/calc") == "pull request on github.com/acme/calc"


def test_the_fix_bug_template_is_valid_and_delivers_to_the_repo_itself(tmp_path):
    from minifactory.core.workflow import load_workflow

    spec = load_workflow(Path(__file__).parents[2] / "src/minifactory/templates/fix-bug/workflow.yaml")
    assert spec.route.delivery == "fixed" and spec.route.intake == "repo-task"
    assert [s.id for s in spec.steps][:6] == ["guard", "clone", "detect", "baseline", "locate", "repro"]
