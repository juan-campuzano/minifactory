from __future__ import annotations

import shutil

from factory.core.context import Step, StepContext, StrictParams
from factory.core.models import Artifact, StepResult
from factory.core.registry import register


class GuardParams(StrictParams):
    branch: str


@register("step", "scm.guard_no_open_pr")
class GuardNoOpenPR(Step):
    """Dedupe: don't redo work that already has a branch or an open PR."""

    Params = GuardParams
    needs = ("scm",)

    def run(self, ctx: StepContext, p: GuardParams) -> StepResult:
        repo = ctx.job.name
        if ctx.scm.branch_exists(repo, p.branch):
            return StepResult.discarded(f"branch {p.branch} already exists")
        if any(pr.get("branch") == p.branch for pr in ctx.scm.open_prs(repo)):
            return StepResult.discarded(f"open PR for {p.branch} already exists")
        return StepResult.ok()


class CloneParams(StrictParams):
    branch: str | None = None  # default: the repo's real default branch


@register("step", "scm.clone")
class Clone(Step):
    Params = CloneParams
    needs = ("scm",)

    def run(self, ctx: StepContext, p: CloneParams) -> StepResult:
        branch = p.branch or ctx.scm.default_branch(ctx.job.name)
        if ctx.repo_dir.exists():
            shutil.rmtree(ctx.repo_dir)
        ctx.scm.clone(ctx.job.name, ctx.repo_dir, branch)
        return StepResult.ok(f"cloned {branch}", branch=branch)


class OpenPRParams(StrictParams):
    branch: str
    title: str
    body: str = ""


@register("step", "scm.open_pr")
class OpenPR(Step):
    """Deliver. Notes collected by earlier steps (e.g. a failed non-blocking coverage
    phase) are appended to the PR description."""

    Params = OpenPRParams
    needs = ("scm",)

    def run(self, ctx: StepContext, p: OpenPRParams) -> StepResult:
        body = p.body
        if ctx.notes:
            body += "\n\n### Factory notes\n" + "\n".join(f"- {n}" for n in ctx.notes)
        url = ctx.scm.push_and_open_pr(ctx.job.name, ctx.repo_dir, p.branch, p.title, body)
        if url is None:
            return StepResult.discarded("no changes to deliver")
        return StepResult(message=url, outputs={"url": url},
                          artifacts=[Artifact(kind=getattr(ctx.scm, "delivery_kind", "pull_request"), ref=url)])


class InitRepoParams(StrictParams):
    pass


@register("step", "scm.init_repo")
class InitRepo(Step):
    """Create the repository for a brand-new project (instead of cloning an existing one)."""

    Params = InitRepoParams
    needs = ("scm",)

    def run(self, ctx: StepContext, p: InitRepoParams) -> StepResult:
        init = getattr(ctx.scm, "init_repo", None)
        if init is None:
            return StepResult.failed(f"scm provider {type(ctx.scm).__name__} cannot create repositories")
        if ctx.repo_dir.exists():
            shutil.rmtree(ctx.repo_dir)
        init(ctx.job.name, ctx.repo_dir)
        return StepResult.ok(f"created {ctx.job.name}")
