"""Workflow templates shipped with the package (`factory/templates/<name>/`). They are starting
points, not active workflows: `minifactory workflows copy NAME` puts one into your workspace, and only
then can `minifactory ask` choose it.

    <name>/workflow.yaml   becomes <workspace>/workflows/<name>.yaml
    <name>/assets/...      copied to the workspace root (specs, fixtures: paths the workflow uses)"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .core.errors import FactoryError

TEMPLATES_DIR = Path(__file__).parent / "templates"


@dataclass(frozen=True)
class Template:
    name: str
    description: str
    path: Path


def available() -> dict[str, Template]:
    found = {}
    for folder in sorted(TEMPLATES_DIR.iterdir()):
        workflow = folder / "workflow.yaml"
        if workflow.is_file():
            first = next((ln.lstrip("# ").strip() for ln in workflow.read_text().splitlines()
                          if ln.startswith("#")), "")
            found[folder.name] = Template(folder.name, first, folder)
    return found


def copy(name: str, workspace_root: Path, workflows_dir: str = "workflows") -> list[Path]:
    """Copy a template into a workspace; returns the files written. A file that already exists is
    skipped when identical (templates share assets) and a conflict, copying nothing, when it differs."""
    templates = available()
    if name not in templates:
        raise FactoryError(f"unknown template '{name}'. Available: {', '.join(templates) or 'none'}")
    source = templates[name].path
    plan = {source / "workflow.yaml": workspace_root / workflows_dir / f"{name}.yaml"}
    assets = source / "assets"
    if assets.is_dir():
        plan |= {f: workspace_root / f.relative_to(assets) for f in sorted(assets.rglob("*")) if f.is_file()}
    clashes = [str(dst) for src, dst in plan.items() if dst.exists() and dst.read_bytes() != src.read_bytes()]
    if clashes:
        raise FactoryError("would overwrite files you changed, nothing copied: " + ", ".join(clashes))
    written = []
    for src, dst in plan.items():
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            written.append(dst)
    return written
