"""`minifactory completion install|uninstall|status`. Every test runs against a throwaway HOME: none may touch
the real dotfiles (ZDOTDIR and XDG_CONFIG_HOME are redirected too, because a real zsh setup often sets them)."""

import shutil
import subprocess

import pytest

from minifactory.cli import shell_setup
from minifactory.cli.commands import main
from minifactory.cli.completion import shell_script


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.delenv("ZDOTDIR", raising=False)
    monkeypatch.setenv("SHELL", "/bin/zsh")
    return tmp_path


# -- planning --------------------------------------------------------------------------------------
@pytest.mark.parametrize("shell_path, expected", [("/bin/zsh", "zsh"), ("/opt/homebrew/bin/bash", "bash"),
                                                   ("/usr/bin/fish", "fish")])
def test_the_shell_is_detected_from_the_environment(shell_path, expected):
    assert shell_setup.detect_shell({"SHELL": shell_path}) == expected


def test_an_unknown_shell_asks_for_an_explicit_choice():
    with pytest.raises(shell_setup.ShellSetupError, match="--shell"):
        shell_setup.detect_shell({"SHELL": "/bin/csh"})
    with pytest.raises(shell_setup.ShellSetupError):
        shell_setup.detect_shell({})


def test_where_each_shell_gets_its_files(home, monkeypatch):
    zsh = shell_setup.plan("zsh")
    assert zsh.rc_path == home / ".zshrc" and zsh.script_path == home / ".config/minifactory/completion/minifactory.zsh"
    monkeypatch.setenv("ZDOTDIR", str(home / "zdot"))
    assert shell_setup.plan("zsh").rc_path == home / "zdot" / ".zshrc"  # ZDOTDIR is respected
    fish = shell_setup.plan("fish")
    assert fish.rc_path is None and fish.script_path == home / ".config/fish/completions/minifactory.fish"


def test_bash_uses_bashrc_else_an_existing_bash_profile_else_creates_bashrc(home):
    assert shell_setup.plan("bash").rc_path == home / ".bashrc"
    (home / ".bash_profile").write_text("")
    assert shell_setup.plan("bash").rc_path == home / ".bash_profile"  # macOS login shells
    (home / ".bashrc").write_text("")
    assert shell_setup.plan("bash").rc_path == home / ".bashrc"


# -- install / uninstall -----------------------------------------------------------------------------
def test_install_writes_the_script_and_a_marked_block_and_keeps_everything_else(home):
    rc = home / ".zshrc"
    rc.write_text("# my zshrc\nexport FOO=1\n")
    shell_setup.install(shell_setup.plan("zsh"))
    text = rc.read_text()
    assert text.startswith("# my zshrc\nexport FOO=1\n") and text.count(shell_setup.BEGIN) == 1
    assert shell_setup.plan("zsh").script_path.read_text() == shell_script("zsh") + "\n"
    assert (home / ".zshrc.minifactory-backup").read_text() == "# my zshrc\nexport FOO=1\n"


def test_install_is_idempotent_and_the_backup_is_made_only_once(home):
    rc = home / ".zshrc"
    rc.write_text("export FOO=1\n")
    p = shell_setup.plan("zsh")
    shell_setup.install(p)
    after_first = rc.read_text()
    rc.write_text(after_first + "export LATER=2\n")  # the user keeps editing
    shell_setup.install(p)
    assert rc.read_text().count(shell_setup.BEGIN) == 1 and "export LATER=2" in rc.read_text()
    assert (home / ".zshrc.minifactory-backup").read_text() == "export FOO=1\n"  # not overwritten


def test_uninstall_restores_the_rc_file_exactly_and_removes_the_script(home):
    rc = home / ".zshrc"
    rc.write_text("# my zshrc\nexport FOO=1\n")
    p = shell_setup.plan("zsh")
    shell_setup.install(p)
    shell_setup.uninstall(p)
    assert rc.read_text() == "# my zshrc\nexport FOO=1\n" and not p.script_path.exists()
    assert shell_setup.uninstall(p) == ["nothing to remove: tab completion was not installed"]


def test_install_into_a_missing_rc_file_creates_it_and_fish_needs_no_rc_edit(home):
    shell_setup.install(shell_setup.plan("zsh"))
    assert shell_shell_has_block(home / ".zshrc")
    shell_setup.install(shell_setup.plan("fish"))
    assert (home / ".config/fish/completions/minifactory.fish").is_file()
    assert not (home / ".config/fish/config.fish").exists()


def shell_shell_has_block(path):
    return path.is_file() and shell_setup.BEGIN in path.read_text() and shell_setup.END in path.read_text()


def test_status_tracks_missing_installed_and_stale(home):
    p = shell_setup.plan("bash")
    assert shell_setup.status("bash") == "missing"
    shell_setup.install(p)
    assert shell_setup.status("bash") == "installed"
    p.script_path.write_text("# an older version of the script\n")
    assert shell_setup.status("bash") == "stale"
    shell_setup.install(p)
    assert shell_setup.status("bash") == "installed"
    p.rc_path.write_text("")  # the user removed the block by hand
    assert shell_setup.status("bash") == "missing"


# -- the real shells accept what we install ------------------------------------------------------------
@pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh not installed")
def test_a_real_zsh_registers_completion_from_the_installed_block_even_without_compinit(home):
    shell_setup.install(shell_setup.plan("zsh"))
    out = subprocess.run(["zsh", "-f", "-c", f'source "{home}/.zshrc"; print -r -- "${{_comps[minifactory]}}"'],
                         capture_output=True, text=True, env={"HOME": str(home), "PATH": "/usr/bin:/bin"}, check=False)
    assert out.stdout.strip() == "_python_argcomplete", out.stderr


@pytest.mark.skipif(not __import__("os").path.exists("/bin/bash"), reason="bash not installed")
def test_a_real_bash_registers_completion_from_the_installed_block(home):
    (home / ".bashrc").write_text("")
    shell_setup.install(shell_setup.plan("bash"))
    out = subprocess.run(["/bin/bash", "-c", f'. "{home}/.bashrc"; complete -p minifactory'],
                         capture_output=True, text=True, env={"HOME": str(home), "PATH": "/usr/bin:/bin"}, check=False)
    assert "_python_argcomplete minifactory" in out.stdout, out.stderr


# -- the command ------------------------------------------------------------------------------------
def test_dry_run_prints_the_plan_and_changes_nothing(home, capsys):
    (home / ".zshrc").write_text("export FOO=1\n")
    assert main(["completion", "install", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "minifactory will:" in out and shell_setup.BEGIN in out and str(home / ".zshrc") in out
    assert (home / ".zshrc").read_text() == "export FOO=1\n" and not shell_setup.plan("zsh").script_path.exists()


def test_without_a_terminal_it_refuses_unless_told_to_go_ahead(home, capsys):
    assert main(["completion", "install"]) == 2  # no TTY under pytest
    assert "--yes" in capsys.readouterr().out and not shell_setup.plan("zsh").script_path.exists()
    assert main(["completion", "install", "--yes"]) == 0
    assert shell_setup.status("zsh") == "installed"
    assert main(["completion", "status"]) == 0 and "installed" in capsys.readouterr().out.splitlines()[-1]
    assert main(["completion", "uninstall", "--yes"]) == 0 and shell_setup.status("zsh") == "missing"


def test_status_says_how_to_fix_a_missing_install(home, capsys):
    assert main(["completion", "status"]) == 0
    assert "missing" in capsys.readouterr().out


def test_an_undetectable_shell_is_a_clear_error_not_a_guess(home, monkeypatch, capsys):
    monkeypatch.setenv("SHELL", "/bin/csh")
    assert main(["completion", "install", "--yes"]) == 2
    assert "--shell" in capsys.readouterr().err
    assert main(["completion", "install", "--shell", "fish", "--yes"]) == 0
    assert shell_setup.status("fish") == "installed"


def test_init_suggests_the_install_only_in_a_terminal_and_only_while_it_is_missing(home, monkeypatch, capsys):
    from minifactory.cli import completion_cmd

    monkeypatch.setattr("sys.stdout.isatty", lambda: False, raising=False)
    completion_cmd.completion_tip()
    assert capsys.readouterr().out == ""  # piped output stays clean
    monkeypatch.setattr("sys.stdout.isatty", lambda: True, raising=False)
    completion_cmd.completion_tip()
    assert "completion install" in capsys.readouterr().out
    shell_setup.install(shell_setup.plan("zsh"))
    completion_cmd.completion_tip()
    assert capsys.readouterr().out == ""  # already installed: no nagging


def test_an_rc_file_we_cannot_write_is_a_clear_error_not_a_traceback(home, capsys):
    rc = home / ".zshrc"
    rc.write_text("export FOO=1\n")
    rc.chmod(0o444)
    try:
        assert main(["completion", "install", "--yes"]) == 2
    finally:
        rc.chmod(0o644)
    err = capsys.readouterr().err
    assert "cannot write" in err and "chown" in err and rc.read_text() == "export FOO=1\n"
