"""Steps for workflows that write other workflows. The drafting agent reads a catalog generated
from the registry, the result must pass the same validator as any workflow, and it is saved as a
DRAFT (never routable, never run) until a person enables it."""

from __future__ import annotations

import re
from pathlib import Path

import minifactory
from minifactory import catalog, stacks, templates
from minifactory.core.context import Step, StepContext, StrictParams
from minifactory.core.errors import FactoryError
from minifactory.core.models import Artifact, StepResult
from minifactory.core.registry import register
from minifactory.core.workflow import load_workflow
from minifactory.review import review

from .util import git

_NAME = re.compile(r"^[a-z][a-z0-9_-]{1,60}$")


class NoParams(StrictParams):
    pass


@register("step", "workdir.init")
class WorkdirInit(Step):
    """Create an empty git repository as the work directory, for workflows that clone nothing."""

    Params = NoParams

    def run(self, ctx: StepContext, p: NoParams) -> StepResult:
        ctx.repo_dir.mkdir(parents=True, exist_ok=True)
        git("init", "--quiet", "-b", "main", cwd=ctx.repo_dir)
        return StepResult.ok("empty repository")


class CatalogParams(StrictParams):
    example: str = "fix-bug"  # a packaged template shown as a working example (EXAMPLE.yaml)


@register("step", "workflow.catalog")
class WriteCatalog(Step):
    """Write CATALOG.md (the format rules and every step and plugin installed, with parameters) and
    EXAMPLE.yaml (a working workflow) into the work directory, for an agent to read."""

    Params = CatalogParams

    def run(self, ctx: StepContext, p: CatalogParams) -> StepResult:
        available = templates.available()
        if p.example not in available:
            return StepResult.failed(f"unknown example template '{p.example}'")
        (ctx.repo_dir / "CATALOG.md").write_text(catalog.render_markdown())
        (ctx.repo_dir / "EXAMPLE.yaml").write_text((available[p.example].path / "workflow.yaml").read_text())
        described = catalog.describe()
        return StepResult.ok(f"CATALOG.md written for minifactory {minifactory.__version__}: "
                             f"{len(described['steps'])} steps, {len(stacks.available())} stacks")


class SaveParams(StrictParams):
    file: str = "draft.yaml"
    dir: str = "workflows/drafts"  # relative to the workspace root (the working directory of a run)


@register("step", "workflow.save_draft")
class SaveDraft(Step):
    """Validate the drafted workflow once more and save it under workflows/drafts/. A draft is not
    routable by `ask` and never runs by itself; `minifactory workflows enable NAME` activates it."""

    Params = SaveParams

    def run(self, ctx: StepContext, p: SaveParams) -> StepResult:
        source = ctx.repo_dir / p.file
        try:
            spec = load_workflow(source)
        except (FactoryError, OSError) as e:
            return StepResult.failed(f"the draft is not a valid workflow: {e}")
        if not _NAME.match(spec.name):
            return StepResult.failed(f"workflow name {spec.name!r} must match {_NAME.pattern}")
        target = Path(p.dir) / f"{spec.name}.yaml"
        if target.exists():
            return StepResult.failed(f"{target} already exists; rename the workflow or remove that draft")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text())
        notes = [str(f) for f in review(spec)]
        ctx.notes.extend(f"review: {n}" for n in notes)
        return StepResult(message=f"saved {target}", outputs={"name": spec.name, "path": str(target)},
                          artifacts=[Artifact(kind="workflow_draft", ref=str(target.resolve()))])
