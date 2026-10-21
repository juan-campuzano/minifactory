"""Shell completion (bash, zsh, fish) through argcomplete.

Tab asks the program itself, so it can offer what exists in YOUR workspace: workflow names, packaged
templates, drafts waiting to be enabled, router plugins. Completion must never break the shell or slow it
down: every completer swallows its own errors, and argcomplete is only imported when the shell asks.

    minifactory completion zsh            # prints the script; see the README for where to put it
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

SHELLS = ("bash", "zsh", "fish")


def _safely(fn: Any) -> Any:
    """A completer that raises would print a traceback into the user's prompt."""

    def wrapped(prefix: str = "", **_: Any) -> list[str]:
        try:
            return [name for name in fn() if name.startswith(prefix)]
        except Exception:  # noqa: BLE001 - nothing a completer does may reach the terminal
            return []

    wrapped.__name__ = getattr(fn, "__name__", "completer")
    return wrapped


def _workflow_dirs() -> list[Path]:
    from minifactory import workspace

    ws = workspace.find()  # find() only reads: unlike a command, completion must not chdir
    return ws.workflow_dirs if ws else [Path.cwd() / "workflows"]


@_safely
def workflow_names() -> list[str]:
    return sorted({f.stem for folder in _workflow_dirs() for f in folder.glob("*.yaml")})


@_safely
def draft_names() -> list[str]:
    return sorted({f.stem for folder in _workflow_dirs() for f in (folder / "drafts").glob("*.yaml")})


@_safely
def template_names() -> list[str]:
    from minifactory import templates

    return sorted(templates.available())


@_safely
def router_names() -> list[str]:
    from minifactory.core import registry

    registry.load_plugins()
    return sorted(registry.catalog()["router"])


def workflows_or_files(prefix: str = "", **kwargs: Any) -> list[str]:
    """A workflow name; or, once you start typing a path (`./`, `~/`, `workflows/`, `x.yaml`), the .yaml files
    and folders there. Offering every folder next to every name would bury the names."""
    names = workflow_names(prefix)
    if not ("/" in prefix or prefix.startswith((".", "~")) or prefix.endswith((".yaml", ".yml"))):
        return names
    from argcomplete.completers import FilesCompleter

    try:
        files = list(FilesCompleter(allowednames=("yaml", "yml"))(prefix=prefix, **kwargs))
    except Exception:  # noqa: BLE001
        files = []
    return names + [f for f in files if f not in names]


def attach(parsers: dict[str, Any]) -> None:
    """Hook the completers onto the arguments that take a name that exists somewhere."""
    for key in ("run.workflow", "validate.workflow", "doctor.workflow"):
        parsers[key].completer = workflows_or_files
    parsers["workflows.copy.name"].completer = template_names
    parsers["workflows.enable.name"].completer = draft_names
    parsers["init.template"].completer = template_names
    parsers["ask.router"].completer = router_names


def shell_script(shell: str, executable: str = "minifactory") -> str:
    """The script that registers completion for `executable` in `shell`."""
    if shell not in SHELLS:
        raise ValueError(f"unsupported shell '{shell}' (expected one of {', '.join(SHELLS)})")
    import argcomplete

    return argcomplete.shellcode([executable], shell=shell)


def activate_if_requested(parser: Any, **options: Any) -> None:
    """Called from main() before parsing. A no-op, without importing argcomplete, unless the shell is asking.
    Options (`-x`, `--long`) are offered only once you type a dash: `minifactory <Tab>` lists commands, not flags."""
    if "_ARGCOMPLETE" not in os.environ:
        return
    try:
        import argcomplete
    except ImportError:
        return
    argcomplete.autocomplete(parser, always_complete_options=False, **options)
