"""`minifactory completion show|install|uninstall|status` and the one-line tip after `init`."""

from __future__ import annotations

import argparse
import sys

from minifactory.core.errors import FactoryError

from . import completion


def completion_tip() -> None:
    """One line, only in a terminal and only when it would help: the install is a command, never automatic."""
    from . import shell_setup

    if not sys.stdout.isatty():
        return
    try:
        if shell_setup.status(shell_setup.detect_shell()) == "missing":
            print("tip: enable tab completion with `minifactory completion install`")
    except FactoryError:
        pass


def run_completion(args: argparse.Namespace) -> int:
    from . import shell_setup

    if args.comp_cmd == "show":
        print(completion.shell_script(args.shell))
        return 0
    shell = args.shell or shell_setup.detect_shell()
    p = shell_setup.plan(shell)
    if args.comp_cmd == "status":
        state = shell_setup.status(shell)
        hint = {"installed": "", "missing": " -> run `minifactory completion install`",
                "stale": " -> run `minifactory completion install` again (the script changed after an upgrade)"}[state]
        print(f"tab completion for {shell}: {state}{hint}")
        return 0
    if args.comp_cmd == "install":
        print("minifactory will:")
        for line in shell_setup.describe(p):
            print(line if line.startswith("    ") else f"  {line}")
        if args.dry_run:
            return 0
    question = "Go ahead?" if args.comp_cmd == "install" else f"Remove tab completion for {shell}?"
    if not args.yes:
        if not sys.stdin.isatty():
            print("not changed (pass --yes to confirm without a terminal)")
            return 2
        if input(f"{question} [y/N] ").strip().lower() != "y":
            print("not changed")
            return 2
    try:
        for line in shell_setup.install(p) if args.comp_cmd == "install" else shell_setup.uninstall(p):
            print(f"  {line}")
    except OSError as e:
        who = getattr(e, "filename", None) or p.rc_path
        raise shell_setup.ShellSetupError(
            f"cannot write {who}: {e.strerror}. Check who owns it (`ls -l {who}`): a file owned by root needs "
            f"`sudo chown $USER {who}`. Do not run minifactory with sudo") from None
    if args.comp_cmd == "install":
        print(f"Open a new terminal (or run `exec {shell}`) to start using it.")
    return 0
