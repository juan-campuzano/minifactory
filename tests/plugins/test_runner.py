"""The runner port: commands run where and how the workflow says, and by default they cannot see credentials."""

import json
import os
import sys
from pathlib import Path

import pytest
import yaml

from minifactory.cli import doctor  # noqa: F401  (keeps the import graph honest: cli may use everything)
from minifactory.core import registry
from minifactory.core.engine import Engine
from minifactory.core.errors import PluginNotFound
from minifactory.core.models import Job
from minifactory.core.workflow import WorkflowSpec, validate_spec
from minifactory.plugins.builtin.providers.runner import HostRunner
from minifactory.plugins.builtin.support.env import filtered
from minifactory.plugins.builtin.support.shell import run_shell
from minifactory.review import review

registry.load_plugins()

SECRETS = {"AWS_SECRET_ACCESS_KEY": "s3cr3t", "AWS_ACCESS_KEY_ID": "AKIAFAKE", "TYPESAFE_API_KEY": "apikey_x",
           "GITHUB_TOKEN": "ghp_x", "GH_TOKEN": "gho_x", "ANTHROPIC_API_KEY": "sk-x", "MY_FLAG": "1", "MY_OTHER": "2"}
DUMP_ENV = f"{sys.executable} -c \"import os, json; print(json.dumps(sorted(os.environ)))\""


@pytest.fixture()
def env_with_secrets(monkeypatch):
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy:3128")
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("FACTORY_FLUTTER", "fake")
    monkeypatch.setenv("JAVA_HOME", "/jdk")


def seen_by(runner, tmp_path) -> set[str]:
    rc, out = runner.run(DUMP_ENV, tmp_path)
    assert rc == 0, out
    return set(json.loads(out))


# -- the environment policy -----------------------------------------------------------------
def test_filtered_keeps_what_a_command_needs_and_drops_credentials():
    environ = {**SECRETS, "PATH": "/bin", "HOME": "/h", "LANG": "C", "LC_ALL": "C", "HTTPS_PROXY": "p",
               "JAVA_HOME": "/jdk", "FACTORY_FLUTTER": "fake", "MINIFACTORY_X": "1", "EDITOR": "vim"}
    kept = filtered(environ)
    needed = {"PATH", "HOME", "LANG", "LC_ALL", "HTTPS_PROXY", "JAVA_HOME", "FACTORY_FLUTTER", "MINIFACTORY_X"}
    assert needed <= set(kept)
    assert not set(SECRETS) & set(kept) and "EDITOR" not in kept


def test_pass_env_adds_exactly_what_was_asked_with_patterns():
    kept = filtered(SECRETS, ["MY_*", "GH_TOKEN"])
    assert set(kept) == {"MY_FLAG", "MY_OTHER", "GH_TOKEN"}


# -- the host runner, with real processes ---------------------------------------------------------
def test_by_default_a_command_cannot_see_your_credentials(env_with_secrets, tmp_path):
    names = seen_by(HostRunner(), tmp_path)
    assert not set(SECRETS) & names, f"leaked: {sorted(set(SECRETS) & names)}"
    tools_and_network = {"PATH", "HOME", "HTTPS_PROXY", "LC_ALL", "JAVA_HOME", "FACTORY_FLUTTER"}
    assert tools_and_network <= names


def test_the_default_policy_also_applies_when_a_step_has_no_runner_at_all(env_with_secrets, tmp_path):
    rc, out = run_shell(DUMP_ENV, tmp_path)
    assert rc == 0 and not set(SECRETS) & set(json.loads(out))


def test_pass_env_lets_chosen_variables_through(env_with_secrets, tmp_path):
    names = seen_by(HostRunner(pass_env=["MY_*"]), tmp_path)
    assert {"MY_FLAG", "MY_OTHER"} <= names and "AWS_SECRET_ACCESS_KEY" not in names


def test_inherit_restores_the_old_behaviour_on_purpose(env_with_secrets, tmp_path):
    assert set(SECRETS) <= seen_by(HostRunner(env="inherit"), tmp_path)


def test_a_bad_env_mode_is_rejected_and_an_empty_command_never_passes(tmp_path):
    with pytest.raises(ValueError, match="minimal"):
        HostRunner(env="everything")
    assert HostRunner().run("  ", tmp_path)[0] != 0


def test_timeouts_are_reported_as_124(tmp_path):
    rc, out = HostRunner().run("sleep 5", tmp_path, timeout=1)
    assert rc == 124 and "timeout" in out


# -- steps go through the workflow's runner ---------------------------------------------------------
class RecordingRunner:
    calls: list[tuple[str, Path]] = []

    def __init__(self, tag: str = ""):
        self.tag = tag

    def run(self, cmd, cwd, timeout=120):
        RecordingRunner.calls.append((cmd, cwd))
        return 0, "recorded"


registry.register("runner", "t.recording")(RecordingRunner)


def engine_for(steps, tmp_path, runner=None):
    data = {"name": "r", "source": {"use": "static", "with": {"jobs": []}}, "steps": steps}
    if runner:
        data["runner"] = runner
    spec = WorkflowSpec.model_validate(data)
    validate_spec(spec)
    return Engine(spec, tmp_path / "runs")


def test_every_command_a_step_runs_goes_through_the_workflows_runner(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    RecordingRunner.calls = []
    engine = engine_for([
        {"id": "init", "use": "workdir.init"},
        {"id": "scaffold", "use": "stack.scaffold"},
        {"id": "analyze", "use": "stack.check", "with": {"check": "analyze"}},
        {"id": "plain", "use": "shell.run", "with": {"cmd": "echo hello"}},
        {"id": "flutter", "use": "flutter.analyze"},
    ], tmp_path, runner={"use": "t.recording"})
    result = engine.run_job(Job(id="j", name="demo_app", attrs={"stack": "flutter"}))
    commands = [c for c, _ in RecordingRunner.calls]
    assert any("flutter_tool create" in c for c in commands), commands  # the scaffold command
    assert any("flutter_tool analyze" in c for c in commands)
    assert "echo hello" in commands
    assert all(cwd.name == "repo" for _, cwd in RecordingRunner.calls)  # always inside the job's repository
    assert {s.id: s.status for s in result.steps} == {"init": "ok", "scaffold": "ok", "analyze": "ok", "plain": "ok",
                                                      "flutter": "ok"}


def test_the_default_runner_is_the_host_one_and_unknown_runners_are_rejected(tmp_path):
    assert isinstance(engine_for([], tmp_path).runner, HostRunner)
    with pytest.raises(PluginNotFound, match="nope"):
        engine_for([], tmp_path, runner={"use": "nope"})


def test_the_workflow_can_configure_the_host_runner(tmp_path):
    engine = engine_for([], tmp_path, runner={"use": "host", "with": {"pass_env": ["MY_*"]}})
    assert engine.runner.pass_env == ["MY_*"]


def test_a_workflow_with_a_runner_key_round_trips_through_yaml(tmp_path):
    spec = WorkflowSpec.model_validate(yaml.safe_load(
        "name: r\nrunner: {use: host, with: {env: inherit}}\nsource: {use: static, with: {jobs: []}}\nsteps: []\n"))
    assert spec.runner.with_ == {"env": "inherit"}


# -- review and docs ---------------------------------------------------------------------------------
def test_review_flags_a_runner_that_widens_the_environment():
    base = {"name": "r", "source": {"use": "static", "with": {"jobs": []}}, "steps": []}
    plain = review(WorkflowSpec.model_validate(base))
    inherit = review(WorkflowSpec.model_validate({**base, "runner": {"use": "host", "with": {"env": "inherit"}}}))
    passing = review(WorkflowSpec.model_validate({**base, "runner": {"use": "host", "with": {"pass_env": ["AWS_*"]}}}))
    assert not any("runner" in str(f) for f in plain)
    assert any("inherit your whole environment" in str(f) for f in inherit)
    assert any("also see: AWS_*" in str(f) for f in passing)


def test_the_os_environment_is_untouched_by_running_commands(env_with_secrets, tmp_path):
    before = dict(os.environ)
    HostRunner().run("true", tmp_path)
    assert dict(os.environ) == before
