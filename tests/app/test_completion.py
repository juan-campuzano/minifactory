"""Tab completion: what the shell is offered, with real argcomplete and the real parser."""

import io
import subprocess
import sys

import argcomplete
import pytest
import yaml

from minifactory import workspace
from minifactory.cli import completion
from minifactory.cli.commands import _parser, main


@pytest.fixture(autouse=True)
def no_fd_9(monkeypatch):
    """By default argcomplete writes its debug output to file descriptor 9 and closes it afterwards. Under pytest
    fd 9 belongs to pytest's faulthandler, so closing it breaks the session (argcomplete documents this)."""
    def use_stderr(self):
        argcomplete.io.debug_stream = sys.stderr

    monkeypatch.setattr(argcomplete.CompletionFinder, "_init_debug_stream", use_stderr)


class Done(Exception):
    """argcomplete exits the process after printing; the tests stop there instead."""


def complete(line: str, monkeypatch) -> list[str]:
    monkeypatch.setenv("_ARGCOMPLETE", "1")
    monkeypatch.setenv("_ARGCOMPLETE_IFS", "\n")
    monkeypatch.setenv("_ARGCOMPLETE_SHELL", "bash")
    monkeypatch.setenv("COMP_LINE", line)
    monkeypatch.setenv("COMP_POINT", str(len(line)))
    out = io.StringIO()

    def stop(code):
        raise Done

    with pytest.raises(Done):
        completion.activate_if_requested(_parser(), exit_method=stop, output_stream=out)
    return [x.rstrip() for x in out.getvalue().split("\n") if x.strip()]  # a trailing space means "finished"


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    workspace.init(tmp_path)
    for name in ("fix-bug", "app-factory"):
        (tmp_path / "workflows" / f"{name}.yaml").write_text(yaml.safe_dump(
            {"name": name, "source": {"use": "static", "with": {"jobs": []}}, "steps": []}))
    (tmp_path / "workflows" / "drafts").mkdir()
    (tmp_path / "workflows" / "drafts" / "my-draft.yaml").write_text("name: my-draft\n")
    (tmp_path / "output").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


# -- what Tab offers ---------------------------------------------------------------------------
def test_commands_are_offered_and_flags_only_after_a_dash(ws, monkeypatch):
    commands = complete("minifactory ", monkeypatch)
    assert {"run", "ask", "validate", "plugins", "init", "workflows", "doctor", "completion"} <= set(commands)
    assert not [c for c in commands if c.startswith("-")]
    assert "--online" in complete("minifactory doctor --o", monkeypatch)
    assert complete("minifactory wor", monkeypatch) == ["workflows"]


def test_workflow_names_come_from_your_workspace_not_from_the_package(ws, monkeypatch):
    for command in ("run", "validate", "doctor"):
        assert set(complete(f"minifactory {command} ", monkeypatch)) == {"fix-bug", "app-factory"}, command
    assert complete("minifactory run fix", monkeypatch) == ["fix-bug"]


def test_a_path_is_completed_as_a_file_only_once_you_start_typing_one(ws, monkeypatch):
    names = complete("minifactory run ", monkeypatch)
    assert not [n for n in names if n.endswith("/")], "folders must not bury the workflow names"
    assert "workflows/fix-bug.yaml" in complete("minifactory run workflows/fi", monkeypatch)


def test_templates_and_drafts_have_their_own_completion(ws, monkeypatch):
    assert {"app-factory", "fix-bug", "create-workflow"} <= set(complete("minifactory workflows copy ", monkeypatch))
    assert complete("minifactory workflows enable ", monkeypatch) == ["my-draft"]
    assert "app-factory" in complete("minifactory init --template ", monkeypatch)


def test_choices_and_plugin_names(ws, monkeypatch):
    assert set(complete("minifactory ask --router ", monkeypatch)) >= {"jev", "keyword"}
    assert set(complete("minifactory ask --output ", monkeypatch)) == {"local", "github"}
    assert set(complete("minifactory completion ", monkeypatch)) == {"bash", "zsh", "fish"}


def test_without_a_workspace_it_still_works(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.chdir(tmp_path)
    assert complete("minifactory run ", monkeypatch) == []
    assert "app-factory" in complete("minifactory workflows copy ", monkeypatch)


def test_a_broken_config_never_reaches_the_terminal(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    (tmp_path / "minifactory.yaml").write_text("workflow_dir: typo\n")
    monkeypatch.chdir(tmp_path)
    assert complete("minifactory run ", monkeypatch) == []  # no traceback, just nothing to offer


# -- the scripts ---------------------------------------------------------------------------------
def test_completion_prints_a_script_for_each_shell(capsys):
    for shell, marker in (("bash", "complete"), ("zsh", "compdef"), ("fish", "complete --command minifactory")):
        assert main(["completion", shell]) == 0
        script = capsys.readouterr().out
        assert "minifactory" in script and marker in script, shell


def test_an_unsupported_shell_is_rejected_by_the_parser(capsys):
    with pytest.raises(SystemExit):
        main(["completion", "tcsh"])
    assert "invalid choice" in capsys.readouterr().err


def test_completion_costs_nothing_when_nobody_asks():
    """argcomplete must not even be imported on a normal run (the CLI starts in ~90 ms and should stay there)."""
    code = ("import sys; from minifactory.cli import main; main(['plugins']); "
            "print('argcomplete' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.split()
    assert out[-1] == "False"
