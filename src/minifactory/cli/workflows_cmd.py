"""`minifactory workflows list|copy|enable` and how a workflow name or path is resolved."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from minifactory import templates, workspace
from minifactory.core.errors import FactoryError
from minifactory.core.workflow import load_workflow


def resolve_workflow(name: str, dirs: list[Path]) -> str:
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
                       "See `minifactory workflows list`")


def enable(args: argparse.Namespace, ws: workspace.Workspace | None) -> int:
    """Show what a drafted workflow would do, then move it into the active workflows folder."""
    from minifactory.review import review

    if ws is None:
        raise FactoryError("no workspace here. Run `minifactory init` first")
    folder = ws.root / ws.config.workflows_dir
    draft, target = folder / "drafts" / f"{args.name}.yaml", folder / f"{args.name}.yaml"
    if not draft.is_file():
        raise FactoryError(f"no draft named '{args.name}' in {draft.parent}")
    if target.exists():
        raise FactoryError(f"{target} already exists; remove or rename one of them first")
    spec = load_workflow(draft)  # a draft written under other plugins may no longer validate
    print(f"workflow '{spec.name}' ({len(spec.steps)} steps) would be enabled. Review:")
    for finding in review(spec):
        print(f"  {finding}")
    if not args.yes and (not sys.stdin.isatty() or input("Enable it? [y/N] ").strip().lower() != "y"):
        print("not enabled (confirm interactively or pass --yes)")
        return 2
    draft.rename(target)
    print(f"enabled: {target.relative_to(ws.root)}")
    return 0


def run_workflows(args: argparse.Namespace, ws: workspace.Workspace | None) -> int:
    if args.wf_cmd == "copy":
        if ws is None:
            raise FactoryError("no workspace here. Run `minifactory init` first")
        for path in templates.copy(args.name, ws.root, ws.config.workflows_dir):
            print(f"  + {path.relative_to(ws.root)}")
        return 0
    if args.wf_cmd == "enable":
        return enable(args, ws)
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
    drafts = [f for folder in args.workflow_dirs for f in sorted((folder / "drafts").glob("*.yaml"))]
    if drafts:
        print("\ndrafts (not routable until `minifactory workflows enable NAME`):")
        for f in drafts:
            print(f"  {f.stem:<32} {f}")
    print("\ntemplates (copy with `minifactory workflows copy NAME`):")
    for t in templates.available().values():
        print(f"  {t.name:<32} {t.description}")
    return 0
