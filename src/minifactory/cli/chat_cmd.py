"""`minifactory chat`: the same flow as `ask`, as a conversation instead of one command per request.

Each line you type is a request: it is routed, its input is drafted, and you are shown what would happen and asked
before anything runs (exactly as `ask` does; there is no `--yes` here). What is new is the conversation around it:
when something is missing (the repository, the pull request number) it fills it in from what you did earlier in the
conversation, or asks for it, and retries instead of failing; `/commands` let you look around without leaving.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
from typing import Any

from minifactory import ask as routing
from minifactory.core.errors import FactoryError, RoutingError

from .ask_flow import run_ask
from .chat_memory import Session

HELP = """\
Type what you need, in your own words:  review PR 285 in acme/app  ·  add a --json flag to acme/textkit
  /workflows   what I can do for you        /history  what we did in this chat
  /last        details of the last one      /forget   clear what I remember
  /help        this text                    /exit     leave (also Ctrl-D); Ctrl-C cancels what is running
If you leave out the repository or the PR, I use the ones from earlier and tell you.
Before anything runs I show what I understood and ask. Nothing is published without your yes."""
MAX_FOLLOW_UPS = 2  # how many times a request may be completed with extra details before giving up


HISTORY_FILE = ".minifactory/chat_history"  # what you typed, for the up arrow in the next session


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


def _handle(console: Any, args: argparse.Namespace, session: Session, request: str) -> None:
    """One request. If it fails for lack of detail, first try what the conversation already knows (the last repository
    and pull request); then ask the user. Anything else is reported."""
    follow_ups, used_memory = 0, False
    while True:
        try:
            run_ask(_ask_args(args, request), session)
            return
        except RoutingError as problem:
            if not used_memory:
                used_memory = True
                filled, added = session.fill(request)
                if added:
                    console.print(f"[dim]({problem}) Trying with {added} from earlier in this chat.[/]")
                    request = filled
                    continue
            console.print(f"[yellow]{problem}[/]")
            if follow_ups == MAX_FOLLOW_UPS:
                return
            more = input("Add details to try again (empty to drop it): ").strip()
            if not more:
                return
            follow_ups += 1
            request = f"{request}\n{more}"
        except FactoryError as e:
            console.print(f"[red]error:[/] {e}")
            return


def _show_last(console: Any, session: Session) -> None:
    if not session.turns:
        console.print("[dim]nothing yet[/]")
        return
    turn = session.turns[-1]
    console.print(f"[bold]{turn.workflow}[/] on {turn.job.name} at {turn.at}: {turn.outcome} {turn.detail}")
    for key, value in turn.job.attrs.items():
        console.print(f"  {key}: {str(value)[:200]}")
    if turn.report:
        console.print(f"\n{turn.report}", markup=False)


def _load_history() -> None:
    with contextlib.suppress(ImportError, OSError):
        import atexit
        import readline
        from pathlib import Path

        path = Path(HISTORY_FILE)
        if path.is_file():
            readline.read_history_file(path)
        readline.set_history_length(500)

        def save() -> None:
            with contextlib.suppress(OSError):
                path.parent.mkdir(parents=True, exist_ok=True)
                readline.write_history_file(path)

        atexit.register(save)


def run_chat(args: argparse.Namespace) -> int:
    from rich.console import Console

    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("error: `minifactory chat` needs a terminal (use `minifactory ask` in scripts)", file=sys.stderr)
        return 2
    _load_history()  # also turns on line editing for input()
    session = Session()
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
        elif line == "/history":
            console.print("\n".join(session.lines()) or "[dim]nothing yet[/]", markup=False)
        elif line == "/last":
            _show_last(console, session)
        elif line == "/forget":
            session.forget()
            console.print("[dim]forgotten[/]")
        elif line.startswith("/"):
            console.print(f"[yellow]unknown command {line.split()[0]}[/] (try /help)")
        else:
            try:
                _handle(console, args, session, line)
            except KeyboardInterrupt:
                console.print("\n[yellow]cancelled[/]")
            except EOFError:
                return 0
