"""`minifactory ask`: free text -> workflow -> drafted input -> confirmation -> run."""

from __future__ import annotations

import sys

from minifactory.core import registry
from minifactory.core.engine import Engine
from minifactory.core.errors import RoutingError, VagueRequest
from minifactory.core.events import EventBus

from .execution import execute


def pick_output(console, args) -> str | None:
    console.print(f"Where should the result go?\n  1. local folder ({args.output_dir}/<name>)\n"
                  f"  2. a new {'PUBLIC' if args.public else 'private'} GitHub repository + pull request")
    answer = input("Choose 1 or 2 (empty to abort): ").strip()
    if answer not in ("1", "2"):
        console.print("aborted")
        return None
    return "local" if answer == "1" else "github"


def run_ask(args) -> int:
    from rich.console import Console

    from minifactory import ask as R
    from minifactory.cli.ui import show_decision, show_spec

    console = Console()
    routables = R.discover(args.workflow_dirs)
    router = registry.get("router", args.router)()
    decision = router.choose(args.request, [r.candidate for r in routables.values()])
    show_decision(console, decision, args.threshold)
    if decision.usage:
        console.print(f"[dim]router tokens: {decision.usage}[/]")

    interactive = sys.stdin.isatty() and not args.yes
    try:
        R.check(decision, args.threshold)
        choice = decision.choice
    except VagueRequest as problem:
        if not interactive:
            raise
        console.print(f"[yellow]{problem}[/] (you can still review the drafted input below)")
        choice = decision.choice
    except RoutingError as problem:
        ranking = [n for n, _ in R.ranked(decision) if n in routables]
        if not interactive or not ranking:
            raise
        console.print(f"[yellow]{problem}[/]")
        for i, name in enumerate(ranking, 1):
            console.print(f"  {i}. {name}")
        answer = input("Pick a workflow number (empty to abort): ").strip()
        if not answer.isdigit() or not 1 <= int(answer) <= len(ranking):
            console.print("aborted")
            return 2
        choice = ranking[int(answer) - 1]

    chosen = routables[choice]
    drafting = Engine(chosen.spec, args.runs_dir, EventBus())  # only for its llm provider
    engine = drafting
    if engine.llm is None:
        raise RoutingError(f"workflow '{chosen.spec.name}' has no llm provider to draft its input")
    intake = registry.get("intake", chosen.spec.route.intake)()
    try:
        job = intake.build(args.request, engine.llm)
    except ValueError as e:
        raise RoutingError(str(e)) from None
    show_spec(console, chosen.spec.name, job)

    output = args.output
    if chosen.spec.route.delivery == "fixed":
        if output:
            raise RoutingError("this workflow delivers to the repository itself; --output does not apply")
        bus = EventBus()
        engine = Engine(chosen.spec, args.runs_dir, bus)
        describe = getattr(engine.scm, "target", lambda repo: repo)  # `target` is optional on providers
        console.print(f"[bold]delivery →[/] {describe(job.name)}")
        if args.dry_run:
            return 0
        if not args.yes and (not sys.stdin.isatty() or input("Run it? [y/N] ").strip().lower() != "y"):
            console.print("not run (confirm interactively or pass --yes)")
            return 2
        execute(engine, bus, [job], args)
        return 0
    if output is None and not args.dry_run:
        if not interactive:
            raise RoutingError("choose where the result goes: --output local|github")
        output = pick_output(console, args)
        if output is None:
            return 2
    bus = EventBus()
    if output:
        spec = R.with_output(chosen.spec, output, output_dir=args.output_dir, owner=args.owner,
                             public=args.public)
        engine = Engine(spec, args.runs_dir, bus)
        console.print(f"[bold]output →[/] {engine.scm.target(job.name)}")
        if output == "github" and args.public:
            console.print("[bold red]this repository will be PUBLIC[/]")
    if args.dry_run:
        return 0
    if not args.yes and (not sys.stdin.isatty() or input("Run it? [y/N] ").strip().lower() != "y"):
        console.print("not run (confirm interactively or pass --yes)")
        return 2
    execute(engine, bus, [job], args)
    return 0
