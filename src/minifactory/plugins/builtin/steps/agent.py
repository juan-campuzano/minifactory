"""Agentic steps. The LLM is non-deterministic, so every agent step is bounded by budgets
and the workflow follows it with a deterministic gate (a build), never trusts it blindly."""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from minifactory import skills, stacks
from minifactory.core.context import Step, StepContext, StrictParams
from minifactory.core.models import StepResult
from minifactory.core.registry import register
from minifactory.plugins.builtin.steps.stack import optional_profile, skill_note
from minifactory.plugins.builtin.support.edits import (
    SYSTEM_PROMPT,
    PatchError,
    apply_edits,
    apply_reply,
    collect_files,
    file_blocks,
    parse_edits,
)
from minifactory.plugins.builtin.support.git import commit_all
from minifactory.plugins.builtin.support.shell import run_cmd
from minifactory.plugins.builtin.support.text import first_json_object as _first_json_object


class MigrateParams(StrictParams):
    instruction: str
    files: list[str]
    commit_message: str = "chore: automated migration"


@register("step", "agent.llm_migrate")
class LLMMigrate(Step):
    """One LLM call that rewrites the listed files following an instruction (a migration), then commits."""

    Params = MigrateParams
    needs = ("llm",)

    def run(self, ctx: StepContext, p: MigrateParams) -> StepResult:
        prompt = f"TASK: migrate\n{p.instruction}\n\n{file_blocks(ctx.repo_dir, p.files)}"
        edits = parse_edits(ctx.llm.complete(SYSTEM_PROMPT, prompt))
        if not edits:
            return StepResult.failed("LLM returned no edits")
        changed = apply_edits(ctx.repo_dir, edits)
        commit_all(ctx.repo_dir, p.commit_message)
        return StepResult.ok(f"edited {', '.join(changed)}", edited=changed)


class RepairParams(StrictParams):
    verify_cmd: str = ""  # a shell command, or leave empty and use `stack` + `checks`
    stack: str | None = None
    checks: list[str] = Field(default_factory=list)  # e.g. [analyze, test]: the stack's commands, run in order
    new_project: bool = False  # true when repairing a project this workflow just created (layout rules apply)
    files: list[str] = Field(default_factory=list)
    globs: list[str] = Field(default_factory=list)  # e.g. lib/**/*.dart, for dynamic file sets
    max_context_chars: int = 60_000
    context: str = ""  # extra guidance shown with every error report (e.g. the rules the file must follow)
    skills: list[str] = Field(default_factory=list)  # installed skills (`minifactory skills add`) shown to the LLM
    max_attempts: int = 5
    max_unproductive: int = 2
    commit_message: str = "fix: repair build after migration"
    timeout: int = 120


@register("step", "agent.repair_build")
class RepairBuild(Step):
    """verify -> ask LLM -> apply -> verify, until green or a budget runs out.

    max_attempts:      hard cap on LLM calls.
    max_unproductive:  consecutive attempts that neither fixed the build nor changed
                       the error (anti-loop).
    """

    Params = RepairParams
    needs = ("llm",)

    def run(self, ctx: StepContext, p: RepairParams) -> StepResult:
        profile = optional_profile(ctx, p.stack)
        verify_cmd = p.verify_cmd
        if not verify_cmd and profile and p.checks:
            name = stacks.project_name(ctx.job.name)
            verify_cmd = " && ".join(stacks.render(profile.commands[c], name=name)
                                     for c in p.checks if c in profile.commands)
        if not verify_cmd:
            return StepResult.failed("repair_build needs `verify_cmd`, or a stack with `checks` it has commands for")
        globs = p.globs or (profile.context_globs if profile and not p.files else [])
        if not p.files and not globs:
            return StepResult.failed("repair_build needs `files` and/or `globs` (or a stack)")
        context = p.context or (stacks.guidance(profile, stacks.project_name(ctx.job.name), new_project=p.new_project)
                                if profile else "")
        try:
            context += skill_note(ctx, p.skills)
        except skills.SkillError as e:
            return StepResult.failed(str(e))
        rc, out = run_cmd(ctx, verify_cmd, p.timeout)
        unproductive = 0
        for attempt in range(1, p.max_attempts + 1):
            if rc == 0:
                return StepResult.ok(f"green after {attempt - 1} attempt(s)", attempts=attempt - 1)
            files = collect_files(ctx.repo_dir, p.files, globs, p.max_context_chars)
            guidance = f"{context}\n\n" if context else ""
            prompt = (f"TASK: repair\nAPP: {ctx.job.name}\n{guidance}The build fails with:\n{out}\n\n"
                      f"{file_blocks(ctx.repo_dir, files)}")
            try:
                edits = apply_reply(ctx.repo_dir, ctx.llm.complete(SYSTEM_PROMPT, prompt))
            except PatchError as e:  # a patch that doesn't apply is an unproductive attempt, not a crash
                edits = []
                ctx.emit("repair_patch_rejected", attempt=attempt, error=str(e))
            if edits:
                commit_all(ctx.repo_dir, p.commit_message)
            new_rc, new_out = run_cmd(ctx, verify_cmd, p.timeout)
            progressed = bool(edits) and (new_rc == 0 or new_out != out)
            unproductive = 0 if progressed else unproductive + 1
            ctx.emit("repair_attempt", attempt=attempt, edits=len(edits), green=new_rc == 0)
            rc, out = new_rc, new_out
            if rc != 0 and unproductive >= p.max_unproductive:
                return StepResult.failed(
                    f"gave up: {unproductive} unproductive attempts. Last error: "
                    f"{out.splitlines()[-1] if out else '?'}", attempts=attempt)
        if rc == 0:
            return StepResult.ok(f"green after {p.max_attempts} attempt(s)", attempts=p.max_attempts)
        return StepResult.failed(f"budget exhausted ({p.max_attempts} attempts)",
                                 attempts=p.max_attempts)


# -- creating an app from a spec: plan, then implement feature by feature --------------------


MAX_FEATURES = 10  # the plan limit and the implement budget must agree


class Feature(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    title: str
    files: list[str] = Field(min_length=1)  # files the feature is expected to touch


class AppPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    features: list[Feature] = Field(min_length=1, max_length=MAX_FEATURES)


# How many features a plan may have, by the size the user asked for ("a minimal app" is not "a full-featured app").
SIZE_BUDGET = {"minimal": 2, "standard": 5, "full": MAX_FEATURES - 2}
SIZE_HINT = {
    "minimal": "A minimal app: one or two screens at most. Prefer a SINGLE feature that holds the screen, "
               "its logic and its tests; never split a model, a button or a theme into their own features.",
    "standard": "A regular app: a handful of coherent features.",
    "full": "A full-featured app: every requested capability, still as small vertical slices.",
}


class PlanParams(StrictParams):
    stack: str | None = None  # default: the job's `stack`
    skills: list[str] = Field(default_factory=list)  # installed skills (`minifactory skills add`) shown to the LLM


@register("step", "agent.plan_app")
class PlanApp(Step):
    """Spec -> validated list of features, sized to what the user asked for. The LLM output is
    untrusted: it is parsed and validated with pydantic, and anything malformed fails the job here,
    not three steps later. A plan over the size budget gets one chance to be redone smaller."""

    Params = PlanParams
    needs = ("llm",)

    def run(self, ctx: StepContext, p: PlanParams) -> StepResult:
        spec = ctx.job.attrs
        size = spec.get("size") if spec.get("size") in SIZE_BUDGET else "standard"
        budget = SIZE_BUDGET[size]
        profile = optional_profile(ctx, p.stack)
        name = stacks.project_name(ctx.job.name)
        example = [stacks.render(f, name=name) for f in (profile.file_example if profile else
                                                          ["path/to/source_file", "path/to/test_file"])]
        stack_note = stacks.guidance(profile, name, new_project=True) if profile else ""
        try:
            stack_note += skill_note(ctx, p.skills)
        except skills.SkillError as e:
            return StepResult.failed(str(e))
        requested = "\n".join(f"- {f}" for f in spec.get("features", []))
        prompt = (f"TASK: plan_app\nAPP: {ctx.job.name}\nSIZE: {size}\n{stack_note}"
                  f"DESCRIPTION: {spec.get('description', '')}\nREQUESTED_FEATURES:\n{requested}\n\n"
                  f"{SIZE_HINT[size]} Plan AT MOST {budget} feature(s), each a vertical slice. "
                  "Reply ONLY with JSON, no prose. Example shape: "
                  '{"features": [{"id": "todo_model", "title": "Todo model", '
                  f'"files": {json.dumps(example)}}}]}}. '
                  "Ids are snake_case; files are paths relative to the project root.")
        for _ in range(2):
            reply = ctx.llm.complete(SYSTEM_PROMPT, prompt)
            try:
                plan = AppPlan.model_validate(_first_json_object(reply))
            except ValidationError as e:
                return StepResult.failed(f"invalid plan: {e.error_count()} problem(s), first: "
                                         f"{e.errors()[0]['loc']}: {e.errors()[0]['msg']}")
            except ValueError as e:
                return StepResult.failed(f"invalid plan: {e}")
            if len(plan.features) <= budget:
                return StepResult.ok(f"{len(plan.features)} feature(s) [{size}]",
                                     features=[f.model_dump() for f in plan.features], size=size)
            prompt += (f"\n\nYour plan had {len(plan.features)} features but the limit for a {size} app "
                       f"is {budget}. Merge features into fewer, larger ones and reply again.")
        return StepResult.failed(f"plan has {len(plan.features)} features, over the {size} budget of {budget}")


class ImplementParams(StrictParams):
    features: list[Feature]  # usually `${steps.plan.outputs.features}`
    stack: str | None = None  # default: the job's `stack`
    context_globs: list[str] | None = None  # default: the stack's sources, tests and manifest
    max_features: int = MAX_FEATURES
    max_context_chars: int = 60_000
    skills: list[str] = Field(default_factory=list)  # installed skills (`minifactory skills add`) shown to the LLM


@register("step", "agent.implement_spec")
class ImplementSpec(Step):
    """One LLM call and one commit per feature. The loop lives here, not in the YAML."""

    Params = ImplementParams
    needs = ("llm",)

    def run(self, ctx: StepContext, p: ImplementParams) -> StepResult:
        if len(p.features) > p.max_features:
            return StepResult.failed(f"plan has {len(p.features)} features, budget is {p.max_features}")
        done: list[str] = []
        profile = optional_profile(ctx, p.stack)
        globs = p.context_globs or (profile.context_globs if profile else ["**/*"])
        stack_note = (stacks.guidance(profile, stacks.project_name(ctx.job.name), new_project=True)
                      if profile else "")
        try:
            stack_note += skill_note(ctx, p.skills)
        except skills.SkillError as e:
            return StepResult.failed(str(e))
        for feature in p.features:
            files = collect_files(ctx.repo_dir, [], globs, p.max_context_chars)
            prompt = (f"TASK: implement\nAPP: {ctx.job.name}\n{stack_note}FEATURE: {feature.id}\n"
                      f"TITLE: {feature.title}\nFILES: {', '.join(feature.files)}\n\n"
                      "Implement ONLY this feature, minimally: a few small files and a handful of focused "
                      "tests (not one test per tiny behaviour), reusing what already exists below.\n\n"
                      f"{file_blocks(ctx.repo_dir, files)}")
            try:
                changed = apply_reply(ctx.repo_dir, ctx.llm.complete(SYSTEM_PROMPT, prompt))
            except PatchError as e:
                return StepResult.failed(f"feature '{feature.id}': {e}", implemented=done)
            if not changed:
                return StepResult.failed(f"feature '{feature.id}': LLM returned no edits",
                                         implemented=done)
            commit_all(ctx.repo_dir, f"feat({feature.id}): {feature.title}")
            ctx.emit("feature_implemented", feature=feature.id, files=changed)
            done.append(feature.id)
        return StepResult.ok(f"implemented {', '.join(done)}", implemented=done)
