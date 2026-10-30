"""Language-agnostic project steps. They read a stack profile (see minifactory.stacks), so the same
workflow scaffolds, checks and tests a Python CLI, a Node script, a Java program or a Flutter app."""

from __future__ import annotations

import re
import shutil
from typing import Literal

from minifactory import roles, skills, stacks
from minifactory.core.context import Step, StepContext, StrictParams
from minifactory.core.models import StepResult
from minifactory.core.registry import register
from minifactory.plugins.builtin.support.git import commit_all
from minifactory.plugins.builtin.support.shell import run_cmd, safe_path


def profile_for(ctx: StepContext, name: str | None) -> stacks.StackProfile:
    """The step's `stack` parameter, else the job's (`${job.stack}` is the usual source)."""
    return stacks.get(name or ctx.job.attrs.get("stack"))


def optional_profile(ctx: StepContext, name: str | None) -> stacks.StackProfile | None:
    chosen = name or ctx.job.attrs.get("stack")
    return stacks.get(chosen) if chosen else None


def skill_note(ctx: StepContext, names: list[str]) -> str:
    """The prompt text for the step's `skills` (raises skills.SkillError if one is missing or too big)."""
    note = skills.prompt_block(names)
    if names:
        ctx.emit("skills_used", names=list(dict.fromkeys(names)), chars=len(note))
    return note


def role_note(ctx: StepContext, role_name: str | None, skill_names: list[str] | None = None) -> str:
    """The prompt text for `role` (its persona + its default skills) plus `skill_names`."""
    role = roles.get(role_name) if role_name else None
    merged = [*(role.skills if role else []), *(skill_names or [])]
    out = roles.prompt_block(role) if role else ""
    if role:
        ctx.emit("role_used", role=role.name, llm="custom" if role.name in ctx.llms else "default")
    out += skill_note(ctx, merged)
    return out


def role_bounds(
    role_name: str | None,
    profile: stacks.StackProfile | None,
    *,
    allowed_prefixes: list[str] | None = None,
    tests_only: bool = False,
) -> tuple[list[str] | None, list[str] | None]:
    """(allowed_prefixes, forbid_prefixes) combining the step's settings with the role's."""
    role = roles.get(role_name) if role_name else None
    only_tests = tests_only or bool(role and role.tests_only)
    if only_tests and not profile:
        raise roles.RoleError("`tests_only` needs a stack (its test folders define what is allowed)")
    allowed = [
        *(allowed_prefixes or []),
        *(role.allowed_prefixes if role else []),
        *(profile.test_prefixes if only_tests and profile else []),
    ]
    forbid = list(role.forbid_prefixes) if role and role.forbid_prefixes else []
    return (allowed or None), (forbid or None)


def missing_tools(profile: stacks.StackProfile) -> str:
    gone = [tool for tool in profile.requires if shutil.which(tool) is None]
    return f"the '{profile.name}' stack needs {', '.join(gone)} on PATH" if gone else ""


class DetectParams(StrictParams):
    stack: str | None = None  # pin the stack (e.g. `${vars.stack}`) instead of guessing it; empty = detect


@register("step", "stack.detect")
class Detect(Step):
    """Recognise the stack of a cloned repository from its files. Unknown or ambiguous = fails, so a
    workflow can stop (on_fail: discard) instead of guessing."""

    Params = DetectParams

    def run(self, ctx: StepContext, p: DetectParams) -> StepResult:
        if p.stack:
            return StepResult.ok(f"{p.stack} (pinned)", stack=stacks.get(p.stack).name)
        found = stacks.detect(ctx.repo_dir)
        known = ", ".join(stacks.available())
        if not found:
            return StepResult.failed(f"unsupported stack: no profile recognises this repository (known: {known}). "
                                     "Add one as stacks/<name>.yaml")
        if len(found) > 1:
            return StepResult.failed(f"ambiguous stack: {', '.join(found)}. Set the stack explicitly")
        return StepResult.ok(found[0], stack=found[0])


class ScaffoldParams(StrictParams):
    stack: str | None = None
    timeout: int = 300


@register("step", "stack.scaffold")
class Scaffold(Step):
    """Seed a new project: write the profile's starter files (never over existing ones), run its
    scaffold commands, commit."""

    Params = ScaffoldParams

    def run(self, ctx: StepContext, p: ScaffoldParams) -> StepResult:
        profile = profile_for(ctx, p.stack)
        if gone := missing_tools(profile):
            return StepResult.failed(gone)
        name = stacks.project_name(ctx.job.name)
        for rel, content in profile.seed_files.items():
            target = safe_path(ctx.repo_dir, rel)
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(stacks.render(content, name=name))
        for command in profile.scaffold:
            rc, out = run_cmd(ctx, stacks.render(command, name=name), p.timeout)
            if rc != 0:
                return StepResult.failed((out.splitlines() or [f"exit code {rc}"])[-1])
        commit_all(ctx.repo_dir, f"chore: scaffold {profile.name} project")
        return StepResult.ok(f"{profile.name} project '{name}'", project=name, stack=profile.name)


class CheckParams(StrictParams):
    check: Literal["setup", "analyze", "test", "format"]
    stack: str | None = None
    paths: list[str] = []  # for `test`: run only these test files
    repro: bool = False  # for `test`: run only the stack's reproduction test file
    expect_failure: bool = False  # the 'bug is reproduced' gate: must fail, and for the right reason
    timeout: int = 600


@register("step", "stack.check")
class Check(Step):
    """Run one of the stack's commands (setup, analyze, test or format) in the repository. A stack that
    has no such command skips the step."""

    Params = CheckParams

    def run(self, ctx: StepContext, p: CheckParams) -> StepResult:
        profile = profile_for(ctx, p.stack)
        if gone := missing_tools(profile):
            return StepResult.failed(gone)
        paths = p.paths or ([profile.repro_test_path] if p.repro else [])
        key = "test_files" if p.check == "test" and paths else p.check
        if key not in profile.commands:
            return StepResult(status="skipped", message=f"the {profile.name} stack has no '{key}' command")
        command = stacks.render(profile.commands[key], name=stacks.project_name(ctx.job.name), paths=paths)
        rc, out = run_cmd(ctx, command, p.timeout)
        outputs = {"rc": rc, "output": out[-4000:]}
        last = (out.splitlines() or [f"exit code {rc}"])[-1]
        if not p.expect_failure:
            return StepResult.ok("ok", **outputs) if rc == 0 else StepResult.failed(last, **outputs)
        if rc in (124, 127):
            return StepResult.failed(f"could not run: {out[-200:]}", **outputs)
        if rc == 0:
            return StepResult.failed("expected the tests to fail, but they passed", **outputs)
        if any(re.search(pattern, out) for pattern in profile.broken_test_patterns):
            return StepResult.failed("the test does not run (syntax or import error), so it proves nothing", **outputs)
        return StepResult.ok("failed as expected", **outputs)
