from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from minifactory import templates, workspace
from minifactory.core import registry
from minifactory.core.engine import Engine
from minifactory.core.errors import FactoryError
from minifactory.core.events import EventBus
from minifactory.core.workflow import load_workflow

from . import completion
from .ask_flow import run_ask
from .completion_cmd import completion_tip, run_completion
from .execution import execute
from .workflows_cmd import resolve_workflow, run_workflows


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="minifactory", description="Tiny pluggable software factory")
    sub = p.add_subparsers(dest="cmd", required=True)
    names: dict[str, argparse.Action] = {}  # arguments whose value can be completed (see cli/completion.py)

    run = sub.add_parser("run", help="run a workflow over all jobs from its source")
    names["run.workflow"] = run.add_argument(
        "workflow", help="a workflow name (from your workspace) or a path to a .yaml")
    run.add_argument("--runs-dir", help="default: from minifactory.yaml")
    run.add_argument("--resume", action="store_true", help="skip steps already completed (ok)")
    run.add_argument("--only", action="append", default=[], help="job id to run (repeatable)")
    run.add_argument("--limit", type=int, default=0)
    run.add_argument("--plugin", action="append", default=[], help="extra plugin module to import")
    run.add_argument("--quiet", action="store_true", help="hide per-step lines")
    run.add_argument("--plain", action="store_true", help="no colours or live board")

    ask = sub.add_parser("ask", help="describe what you need in plain language; picks and runs a workflow")
    ask.add_argument("request")
    ask.add_argument("--workflows-dir", help="default: the workspace workflows folders")
    names["ask.router"] = ask.add_argument("--router", help="router plugin (default: minifactory.yaml, then jev)")
    ask.add_argument("--threshold", type=float, help="minimum router confidence (default: minifactory.yaml, then 0.7)")
    ask.add_argument("--yes", action="store_true", help="don't ask; only acts when confident and actionable")
    ask.add_argument("--dry-run", action="store_true", help="show the chosen workflow and drafted input, run nothing")
    ask.add_argument("--output", choices=["local", "github"],
                     help="where the result goes (asked interactively if omitted)")
    ask.add_argument("--output-dir", help="parent folder for --output local (default: minifactory.yaml, then output)")
    ask.add_argument("--owner", help="GitHub user or org for --output github (default: your gh login)")
    ask.add_argument("--public", action="store_true", help="make the GitHub repo public (default: private)")
    ask.add_argument("--runs-dir", help="default: from minifactory.yaml")
    ask.add_argument("--plain", action="store_true", help="no colours or live board")
    ask.add_argument("--plugin", action="append", default=[])

    val = sub.add_parser("validate", help="check a workflow without running it")
    names["validate.workflow"] = val.add_argument("workflow", help="a workflow name or a path to a .yaml")
    val.add_argument("--plugin", action="append", default=[])

    pl = sub.add_parser("plugins", help="list registered plugins")
    pl.add_argument("--plugin", action="append", default=[])
    pl.add_argument("--schema", action="store_true",
                    help="print what can be built: every step with its parameters, providers, the format rules")
    pl.add_argument("--json", action="store_true", help="with --schema: machine-readable")

    init = sub.add_parser("init", help="create a workspace (minifactory.yaml + workflows/) in a folder")
    init.add_argument("folder", nargs="?", default=".")
    names["init.template"] = init.add_argument(
        "--template", help="also copy a template workflow (see `minifactory workflows list`)")

    wf = sub.add_parser("workflows", help="list or copy workflows")
    wf_sub = wf.add_subparsers(dest="wf_cmd", required=True)
    wf_sub.add_parser("list", help="your workflows and the templates that ship with the package")
    cp = wf_sub.add_parser("copy", help="copy a packaged template into your workspace")
    names["workflows.copy.name"] = cp.add_argument("name")
    en = wf_sub.add_parser("enable", help="review a drafted workflow and make it active (routable by `ask`)")
    names["workflows.enable.name"] = en.add_argument("name")
    en.add_argument("--yes", action="store_true", help="don't ask for confirmation")

    doc = sub.add_parser("doctor", help="check what is installed and configured; optionally what a workflow needs")
    names["doctor.workflow"] = doc.add_argument(
        "workflow", nargs="?", help="a workflow name or path: check what IT needs")
    doc.add_argument("--online", action="store_true", help="also contact AWS and GitHub (no secrets are printed)")
    doc.add_argument("--json", action="store_true", help="machine-readable output")
    doc.add_argument("--plugin", action="append", default=[])

    comp = sub.add_parser("completion", help="tab completion: install it, or print its script")
    comp_sub = comp.add_subparsers(dest="comp_cmd", required=True)
    show = comp_sub.add_parser("show", help="print the completion script for a shell")
    show.add_argument("shell", choices=completion.SHELLS)
    for name, text in (("install", "enable tab completion in your shell (asks before editing your rc file)"),
                       ("uninstall", "remove what `install` added"),
                       ("status", "is tab completion installed and up to date?")):
        cp_ = comp_sub.add_parser(name, help=text)
        cp_.add_argument("--shell", choices=completion.SHELLS, help="default: from $SHELL")
        if name != "status":
            cp_.add_argument("--yes", action="store_true", help="don't ask for confirmation")
        if name == "install":
            cp_.add_argument("--dry-run", action="store_true", help="show what would change, change nothing")

    demo = sub.add_parser("demo-init", help="create the demo sandbox (git remotes + catalog)")
    demo.add_argument("--dir", default="demo")
    completion.attach(names)
    return p


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


def _doctor(args: argparse.Namespace, ws: workspace.Workspace | None) -> int:
    from minifactory.cli import doctor

    spec = load_workflow(resolve_workflow(args.workflow, args.workflow_dirs)) if args.workflow else None
    checks = doctor.run_checks(doctor.System(), ws, workflow=spec, online=args.online)
    if args.json:
        import json

        print(json.dumps(doctor.as_json(checks), indent=2))
    else:
        from rich.console import Console

        doctor.render(checks, Console())
    return doctor.exit_code(checks)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    completion.activate_if_requested(parser)  # only does anything when the shell is asking for completions
    args = parser.parse_args(argv)
    try:
        if args.cmd == "completion":
            return run_completion(args)

        if args.cmd == "init":
            folder = Path(args.folder)
            created = workspace.init(folder)
            if args.template:
                root = folder.resolve()
                created += [str(p.relative_to(root)) for p in templates.copy(args.template, root)]
            print(f"workspace ready in {folder.resolve()}" + "".join(f"\n  + {c}" for c in created))
            completion_tip()
            return 0

        ws = _use_workspace(args)
        registry.load_plugins(args.plugin)
        if args.cmd == "workflows":
            return run_workflows(args, ws)
        if args.cmd == "doctor":
            return _doctor(args, ws)

        if args.cmd == "demo-init":
            from minifactory.cli.demo import demo_init

            path = demo_init(args.dir)
            print(f"demo sandbox ready in ./{path}")
            return 0

        if args.cmd == "plugins" and args.schema:
            from minifactory import catalog as plugin_catalog

            if args.json:
                import json

                print(json.dumps(plugin_catalog.describe(), indent=2, default=str))
            else:
                print(plugin_catalog.render_markdown())
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
            return run_ask(args)

        spec = load_workflow(resolve_workflow(args.workflow, args.workflow_dirs))
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
        execute(engine, bus, jobs, args)
        return 0
    except FactoryError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
