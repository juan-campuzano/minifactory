"""`minifactory completion install|uninstall|status`: enabling tab completion without hand-editing dotfiles.

Package managers run nothing when they install a package, so this cannot happen by itself; it is a command.
It is careful because it edits a file you own:
  - the script lives in a file of ours (`<config>/minifactory/completion/`), and your rc file only gets a small
    block between two marker lines that `uninstall` removes again. Startup stays fast (no python at shell start);
  - fish needs no rc edit: its completions folder is autoloaded;
  - it is idempotent, keeps a one-time backup of the rc file, and `--dry-run` shows everything first.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from minifactory import workspace
from minifactory.core.errors import FactoryError

from .completion import SHELLS, shell_script

BEGIN = "# >>> minifactory completion >>>"
END = "# <<< minifactory completion <<<"
Status = Literal["installed", "stale", "missing"]


class ShellSetupError(FactoryError):
    pass


@dataclass(frozen=True)
class Plan:
    shell: str
    script_path: Path  # the completion script we write
    rc_path: Path | None  # the file that gets a block (None for fish)
    block: str  # what goes in the rc file ("" for fish)


def detect_shell(environ: dict[str, str] | None = None) -> str:
    name = Path((os.environ if environ is None else environ).get("SHELL", "")).name
    if name not in SHELLS:
        raise ShellSetupError(
            f"cannot tell your shell from $SHELL ({name or 'not set'}): pass --shell {'|'.join(SHELLS)}")
    return name


def _config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def _rc_for(shell: str) -> Path:
    if shell == "zsh":
        return Path(os.environ.get("ZDOTDIR") or Path.home()) / ".zshrc"
    # macOS terminals start login shells, which read .bash_profile, not .bashrc
    for name in (".bashrc", ".bash_profile"):
        if (Path.home() / name).exists():
            return Path.home() / name
    return Path.home() / ".bashrc"


def plan(shell: str) -> Plan:
    if shell not in SHELLS:
        raise ShellSetupError(f"unsupported shell '{shell}' (expected one of {', '.join(SHELLS)})")
    if shell == "fish":
        return Plan(shell, _config_home() / "fish" / "completions" / "minifactory.fish", None, "")
    script = workspace.global_dir() / "completion" / f"minifactory.{shell}"
    if shell == "zsh":
        body = ('(( $+functions[compdef] )) || { autoload -Uz compinit && compinit -u; }\n'
                f'[[ -f "{script}" ]] && source "{script}"')
    else:
        body = f'[ -f "{script}" ] && . "{script}"'
    note = "# Tab completion for minifactory. Remove it with `minifactory completion uninstall`."
    block = f"{BEGIN}\n{note}\n{body}\n{END}"
    return Plan(shell, script, _rc_for(shell), block)


def _has_block(text: str) -> bool:
    return BEGIN in text and END in text


def status(shell: str) -> Status:
    p = plan(shell)
    if not p.script_path.is_file():
        return "missing"
    if p.rc_path is not None and not (p.rc_path.is_file() and _has_block(p.rc_path.read_text())):
        return "missing"
    return "installed" if p.script_path.read_text() == shell_script(shell) + "\n" else "stale"


def _with_block(text: str, block: str) -> str:
    if _has_block(text):
        head, rest = text.split(BEGIN, 1)
        return head + block + rest.split(END, 1)[1]
    return text + ("" if text.endswith("\n") or not text else "\n") + ("\n" if text else "") + block + "\n"


def _without_block(text: str) -> str:
    if not _has_block(text):
        return text
    head, rest = text.split(BEGIN, 1)
    return head.rstrip("\n") + ("\n" if head.strip() else "") + rest.split(END, 1)[1].lstrip("\n")


def describe(p: Plan) -> list[str]:
    lines = [f"write the {p.shell} completion script to {p.script_path}"]
    if p.rc_path is not None:
        lines.append(f"add this block to {p.rc_path} (replaced if it is already there; the file is backed up once):")
        lines += [f"    {ln}" for ln in p.block.splitlines()]
    return lines


def install(p: Plan) -> list[str]:
    done = []
    p.script_path.parent.mkdir(parents=True, exist_ok=True)
    p.script_path.write_text(shell_script(p.shell) + "\n")
    done.append(f"wrote {p.script_path}")
    if p.rc_path is not None:
        existing = p.rc_path.read_text() if p.rc_path.is_file() else ""
        backup = p.rc_path.with_name(p.rc_path.name + ".minifactory-backup")
        if existing and not backup.exists():
            shutil.copy2(p.rc_path, backup)
            done.append(f"backed up {p.rc_path.name} to {backup.name}")
        updated = _with_block(existing, p.block)
        if updated != existing:
            p.rc_path.parent.mkdir(parents=True, exist_ok=True)
            p.rc_path.write_text(updated)
            done.append(f"updated {p.rc_path}")
        else:
            done.append(f"{p.rc_path.name} already had the block")
    return done


def uninstall(p: Plan) -> list[str]:
    done = []
    if p.rc_path is not None and p.rc_path.is_file() and _has_block(p.rc_path.read_text()):
        p.rc_path.write_text(_without_block(p.rc_path.read_text()))
        done.append(f"removed the block from {p.rc_path}")
    if p.script_path.is_file():
        p.script_path.unlink()
        done.append(f"deleted {p.script_path}")
    return done or ["nothing to remove: tab completion was not installed"]
