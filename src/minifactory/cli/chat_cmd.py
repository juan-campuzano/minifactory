"""`minifactory chat`: the same flow as `ask`, as a conversation instead of one command per request.

Each line you type is a request: it is routed, its input is drafted, and you are shown what would happen and asked
before anything runs (exactly as `ask` does; there is no `--yes` here). What is new is the conversation around it:
when something is missing (the repository, the pull request number) it asks for it and retries with your answer
added, instead of failing, and `/commands` let you look around without leaving.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
from typing import Any

from minifactory import ask as routing
from minifactory.core.errors import FactoryError, RoutingError

from .ask_flow import run_ask

HELP = """\
Type what you need, in your own words:  review PR 285 in acme/app  ·  add a --json flag to acme/textkit
  /workflows   what I can do for you        /help   this text
  /exit        leave (also Ctrl-D)          Ctrl-C  cancel what you are typing or what is running
Before anything runs I show what I understood and ask. Nothing is published without your yes."""
MAX_FOLLOW_UPS = 2  # how many times a request may be completed with extra details before giving up


def _ask_args(args: argparse.Namespace, request: str) -> argparse.Namespace:
    """What `run_ask` reads, for one line of the conversation: always interactive, never `--yes`."""
    return argparse.Namespace(**{**vars(args), "request": request, "yes": False, "dry_run": False, "output": None})


def _show_workflows(console: Any, args: argparse.Namespace) -> None:
    try:
        found = routing.discover(args.workflow_dirs)
    except RoutingError as e:
        console.print(f"[yellow]{e}[/]")
        return
    for name, routable in found.items():
        console.print(f"  [bold]{name}[/]  {routable.spec.route.description if routable.spec.route else ''}")
        if routable.spec.route and routable.spec.route.examples:
            console.print(f"      [dim]e.g. {routable.spec.route.examples[0]}[/]")


def _handle(console: Any, args: argparse.Namespace, request: str) -> None:
    """One request. A problem that more details could fix is asked about; anything else is reported."""
    for attempt in range(MAX_FOLLOW_UPS + 1):
        try:
            run_ask(_ask_args(args, request))
            return
        except RoutingError as problem:
            console.print(f"[yellow]{problem}[/]")
            if attempt == MAX_FOLLOW_UPS:
                return
            more = input("Add details to try again (empty to drop it): ").strip()
            if not more:
                return
            request = f"{request}\n{more}"
        except FactoryError as e:
            console.print(f"[red]error:[/] {e}")
            return


def run_chat(args: argparse.Namespace) -> int:
    from rich.console import Console

    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("error: `minifactory chat` needs a terminal (use `minifactory ask` in scripts)", file=sys.stderr)
        return 2
    with contextlib.suppress(ImportError):
        import readline  # noqa: F401 - only for line editing and history in input()
    console = Console(highlight=False)  # no automatic colouring of numbers and paths in what we print
    console.print("[bold]minifactory[/] chat. Describe what you need, or /help.")
    while True:
        try:
            line = input("\nyou › ").strip()
        except EOFError:
            console.print()
            return 0
        except KeyboardInterrupt:
            console.print("\n[dim](Ctrl-D or /exit to leave)[/]")
            continue
        if not line:
            continue
        if line in ("/exit", "/quit"):
            return 0
        if line == "/help":
            console.print(HELP)
        elif line == "/workflows":
            _show_workflows(console, args)
        elif line.startswith("/"):
            console.print(f"[yellow]unknown command {line.split()[0]}[/] (try /help)")
        else:
            try:
                _handle(console, args, line)
            except KeyboardInterrupt:
                console.print("\n[yellow]cancelled[/]")
            except EOFError:
                return 0
