from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from factory import templates, workspace
from factory.core import registry
from factory.core.engine import Engine
from factory.core.errors import FactoryError, RoutingError, VagueRequest
from factory.core.events import ConsoleSink, EventBus
from factory.core.workflow import load_workflow


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="factory", description="Tiny pluggable software factory")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="run a workflow over all jobs from its source")
    run.add_argument("workflow", help="a workflow name (from your workspace) or a path to a .yaml")
    run.add_argument("--runs-dir", help="default: from factory.yaml")
    run.add_argument("--resume", action="store_true", help="skip steps already completed (ok)")
    run.add_argument("--only", action="append", default=[], help="job id to run (repeatable)")
    run.add_argument("--limit", type=int, default=0)
    run.add_argument("--plugin", action="append", default=[], help="extra plugin module to import")
    run.add_argument("--quiet", action="store_true", help="hide per-step lines")
    run.add_argument("--plain", action="store_true", help="no colours or live board")

    ask = sub.add_parser("ask", help="describe what you need in plain language; picks and runs a workflow")
    ask.add_argument("request")
    ask.add_argument("--workflows-dir", help="default: the workspace workflows folders")
    ask.add_argument("--router", help="router plugin (default: factory.yaml, then jev)")
    ask.add_argument("--threshold", type=float, help="minimum router confidence (default: factory.yaml, then 0.7)")
    ask.add_argument("--yes", action="store_true", help="don't ask; only acts when confident and actionable")
    ask.add_argument("--dry-run", action="store_true", help="show the chosen workflow and drafted input, run nothing")
    ask.add_argument("--output", choices=["local", "github"],
                     help="where the result goes (asked interactively if omitted)")
    ask.add_argument("--output-dir", help="parent folder for --output local (default: factory.yaml, then output)")
    ask.add_argument("--owner", help="GitHub user or org for --output github (default: your gh login)")
    ask.add_argument("--public", action="store_true", help="make the GitHub repo public (default: private)")
    ask.add_argument("--runs-dir", help="default: from factory.yaml")
    ask.add_argument("--plain", action="store_true", help="no colours or live board")
    ask.add_argument("--plugin", action="append", default=[])

    val = sub.add_parser("validate", help="check a workflow without running it")
    val.add_argument("workflow", help="a workflow name or a path to a .yaml")
    val.add_argument("--plugin", action="append", default=[])

    pl = sub.add_parser("plugins", help="list registered plugins")
    pl.add_argument("--plugin", action="append", default=[])

    init = sub.add_parser("init", help="create a workspace (factory.yaml + workflows/) in a folder")
    init.add_argument("folder", nargs="?", default=".")
    init.add_argument("--template", help="also copy a template workflow (see `factory workflows list`)")

    wf = sub.add_parser("workflows", help="list or copy workflows")
    wf_sub = wf.add_subparsers(dest="wf_cmd", required=True)
    wf_sub.add_parser("list", help="your workflows and the templates that ship with the package")
    cp = wf_sub.add_parser("copy", help="copy a packaged template into your workspace")
    cp.add_argument("name")

    demo = sub.add_parser("demo-init", help="create the demo sandbox (git remotes + catalog)")
    demo.add_argument("--dir", default="demo")
    return p


def _summary(results) -> None:
    print("\n" + "─" * 78)
    print(f"{'JOB':<22} {'OUTCOME':<10} DETAIL")
    for r in results:
        pr = r.artifacts[0].ref if r.artifacts else ""
        detail = pr or r.reason
        print(f"{r.job_id:<22} {r.outcome:<10} {detail}")
        for note in r.notes:
            print(f"{'':<33} note: {note}")
    counts = {o: sum(r.outcome == o for r in results) for o in ("succeeded", "failed", "discarded")}
    print("─" * 78)
    print("  ".join(f"{k}: {v}" for k, v in counts.items()))


def _execute(engine: Engine, bus: EventBus, jobs, args) -> None:
    """Run jobs with the live board on a terminal, plain lines otherwise."""

    def run_one(job):
        return engine.run_job(job, resume=getattr(args, "resume", False))

    spec = engine.spec
    if sys.stdout.isatty() and not args.plain:
        from factory.ui import LiveBoard, banner

        board = LiveBoard([j.id for j in jobs], [s.id for s in spec.steps])
        banner(board.console)
        board.console.print(f"[bold]{spec.name}[/]  ·  {len(jobs)} job(s)\n")
        bus.subscribe(board)
        with board:
            results = engine.executor.run(jobs, run_one)
        board.summary(results)
        return

    if not getattr(args, "quiet", False):
        bus.subscribe(ConsoleSink())
    print(f"workflow '{spec.name}': {len(jobs)} job(s)")
    results = engine.executor.run(jobs, run_one)
    _summary(results)


def _pick_output(console, args) -> str | None:
    console.print(f"Where should the result go?\n  1. local folder ({args.output_dir}/<name>)\n"
                  f"  2. a new {'PUBLIC' if args.public else 'private'} GitHub repository + pull request")
    answer = input("Choose 1 or 2 (empty to abort): ").strip()
    if answer not in ("1", "2"):
        console.print("aborted")
        return None
    return "local" if answer == "1" else "github"


def _ask(args) -> int:
    from rich.console import Console

    from factory import router as R
    from factory.ui import show_decision, show_spec

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
        _execute(engine, bus, [job], args)
        return 0
    if output is None and not args.dry_run:
        if not interactive:
            raise RoutingError("choose where the result goes: --output local|github")
        output = _pick_output(console, args)
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
    _execute(engine, bus, [job], args)
    return 0


def _use_workspace(args: argparse.Namespace) -> workspace.Workspace | None:
    """Find the workspace, fill unset options from its config and make it the working directory
    (workflows reference specs/, output/... relative to the workspace root). Without a workspace
    everything stays relative to the current directory, as before."""
    ws = workspace.find()
    cfg = ws.config if ws else workspace.FactoryConfig()
    # Paths typed on the command line mean "relative to where I am": make them absolute first.
    wf = getattr(args, "workflow", None)
    if wf and Path(wf).is_file():
        args.workflow = str(Path(wf).resolve())
    explicit = getattr(args, "workflows_dir", None)
    if explicit:
        args.workflow_dirs = [Path(explicit).resolve()]
    elif ws:
        args.workflow_dirs = ws.workflow_dirs
    else:
        args.workflow_dirs = [Path.cwd() / cfg.workflows_dir]
    if ws:
        os.chdir(ws.root)
    for attr, default in (("runs_dir", cfg.runs_dir), ("output_dir", cfg.output_dir),
                          ("router", cfg.router), ("threshold", cfg.threshold)):
        if hasattr(args, attr) and getattr(args, attr) is None:
            setattr(args, attr, default)
    args.plugin = [*cfg.plugins, *getattr(args, "plugin", [])]
    return ws


def _resolve_workflow(name: str, dirs: list[Path]) -> str:
    """A path to a .yaml, or the name of a workflow in the workspace folders."""
    if Path(name).is_file():
        return name
    for folder in dirs:
        for candidate in (folder / name, folder / f"{name}.yaml"):
            if candidate.is_file():
                return str(candidate)
    known = sorted(f.stem for folder in dirs for f in folder.glob("*.yaml"))
    hint = f"your workflows: {', '.join(known)}" if known else "no workflows found"
    ready = ", ".join(templates.available())
    raise FactoryError(f"workflow '{name}' not found ({hint}). Templates you can copy: {ready}. "
                       "See `factory workflows list`")


def _workflows(args: argparse.Namespace, ws: workspace.Workspace | None) -> int:
    if args.wf_cmd == "copy":
        if ws is None:
            raise FactoryError("no workspace here. Run `factory init` first")
        for path in templates.copy(args.name, ws.root, ws.config.workflows_dir):
            print(f"  + {path.relative_to(ws.root)}")
        return 0
    print("your workflows:")
    mine = [f for folder in args.workflow_dirs for f in sorted(folder.glob("*.yaml"))]
    for f in mine:
        try:
            spec = load_workflow(f)
            print(f"  {spec.name:<32} {'routable' if spec.route else 'run only'}   {f}")
        except FactoryError as e:
            print(f"  {f.stem:<32} INVALID: {str(e)[:80]}")
    if not mine:
        print("  (none)")
    print("\ntemplates (copy with `factory workflows copy NAME`):")
    for t in templates.available().values():
        print(f"  {t.name:<32} {t.description}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.cmd == "init":
            folder = Path(args.folder)
            created = workspace.init(folder)
            if args.template:
                root = folder.resolve()
                created += [str(p.relative_to(root)) for p in templates.copy(args.template, root)]
            print(f"workspace ready in {folder.resolve()}" + "".join(f"\n  + {c}" for c in created))
            return 0

        ws = _use_workspace(args)
        registry.load_plugins(args.plugin)
        if args.cmd == "workflows":
            return _workflows(args, ws)

        if args.cmd == "demo-init":
            from factory.demo import demo_init

            path = demo_init(args.dir)
            print(f"demo sandbox ready in ./{path}")
            return 0

        if args.cmd == "plugins":
            catalog = registry.catalog()
            if sys.stdout.isatty():
                from rich.console import Console
                from rich.table import Table

                table = Table(title="registered plugins", header_style="bold magenta")
                table.add_column("kind", style="cyan")
                table.add_column("names")
                for kind, names in catalog.items():
                    table.add_row(kind, "  ".join(names))
                Console().print(table)
            else:
                for kind, names in catalog.items():
                    print(f"{kind:<9} {', '.join(names)}")
            return 0

        if args.cmd == "ask":
            return _ask(args)

        spec = load_workflow(_resolve_workflow(args.workflow, args.workflow_dirs))
        if args.cmd == "validate":
            print(f"workflow '{spec.name}' is valid ({len(spec.steps)} steps)")
            return 0

        bus = EventBus()
        engine = Engine(spec, args.runs_dir, bus)
        jobs = engine.source.jobs()
        if args.only:
            jobs = [j for j in jobs if j.id in args.only]
        if args.limit:
            jobs = jobs[: args.limit]
        _execute(engine, bus, jobs, args)
        return 0
    except FactoryError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
