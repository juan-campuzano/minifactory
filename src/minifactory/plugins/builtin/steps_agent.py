"""Agentic steps. The LLM is non-deterministic, so every agent step is bounded by budgets
and the workflow follows it with a deterministic gate (a build), never trusts it blindly."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from minifactory.core.context import Step, StepContext, StrictParams
from minifactory.core.models import StepResult
from minifactory.core.registry import register

from .util import (
    SYSTEM_PROMPT,
    PatchError,
    apply_edits,
    apply_reply,
    collect_files,
    commit_all,
    file_blocks,
    parse_edits,
    run_shell,
)
from .util import first_json_object as _first_json_object


class MigrateParams(StrictParams):
    instruction: str
    files: list[str]
    commit_message: str = "chore: automated migration"


@register("step", "agent.llm_migrate")
class LLMMigrate(Step):
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
    verify_cmd: str
    files: list[str] = Field(default_factory=list)
    globs: list[str] = Field(default_factory=list)  # e.g. lib/**/*.dart, for dynamic file sets
    max_context_chars: int = 60_000
    max_attempts: int = 5
    max_unproductive: int = 2
    commit_message: str = "fix: repair build after migration"
    timeout: int = 120


@register("step", "agent.repair_build")
class RepairBuild(Step):
    """verify -> ask LLM -> apply -> verify, until green or a budget runs out.

    max_attempts:      hard cap on LLM calls.
    max_unproductive:  consecutive attempts that neither fixed the build nor changed
                       the error (anti-loop). Mirrors your COPILOT_MAX_* budgets.
    """

    Params = RepairParams
    needs = ("llm",)

    def run(self, ctx: StepContext, p: RepairParams) -> StepResult:
        if not p.files and not p.globs:
            return StepResult.failed("repair_build needs `files` and/or `globs`")
        rc, out = run_shell(p.verify_cmd, ctx.repo_dir, p.timeout)
        unproductive = 0
        for attempt in range(1, p.max_attempts + 1):
            if rc == 0:
                return StepResult.ok(f"green after {attempt - 1} attempt(s)", attempts=attempt - 1)
            files = collect_files(ctx.repo_dir, p.files, p.globs, p.max_context_chars)
            prompt = (f"TASK: repair\nAPP: {ctx.job.name}\nThe build fails with:\n{out}\n\n"
                      f"{file_blocks(ctx.repo_dir, files)}")
            try:
                edits = apply_reply(ctx.repo_dir, ctx.llm.complete(SYSTEM_PROMPT, prompt))
            except PatchError as e:  # a patch that doesn't apply is an unproductive attempt, not a crash
                edits = []
                ctx.emit("repair_patch_rejected", attempt=attempt, error=str(e))
            if edits:
                commit_all(ctx.repo_dir, p.commit_message)
            new_rc, new_out = run_shell(p.verify_cmd, ctx.repo_dir, p.timeout)
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


# How many features a plan may have, by the size the user asked for ("una app mínima" != "una app completa").
SIZE_BUDGET = {"minimal": 2, "standard": 5, "full": MAX_FEATURES - 2}
SIZE_HINT = {
    "minimal": "A minimal app: one or two screens at most. Prefer a SINGLE feature that holds the screen, "
               "its logic and its tests; never split a model, a button or a theme into their own features.",
    "standard": "A regular app: a handful of coherent features.",
    "full": "A full-featured app: every requested capability, still as small vertical slices.",
}


class PlanParams(StrictParams):
    pass


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
        requested = "\n".join(f"- {f}" for f in spec.get("features", []))
        prompt = (f"TASK: plan_app\nAPP: {ctx.job.name}\nSIZE: {size}\n"
                  f"DESCRIPTION: {spec.get('description', '')}\nREQUESTED_FEATURES:\n{requested}\n\n"
                  f"{SIZE_HINT[size]} Plan AT MOST {budget} feature(s), each a vertical slice. "
                  "Reply ONLY with JSON, no prose. Example shape: "
                  '{"features": [{"id": "todo_model", "title": "Todo model", '
                  '"files": ["lib/todo.dart", "test/todo_test.dart"]}]}. '
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
    context_globs: list[str] = Field(default_factory=lambda: ["lib/**/*.dart", "test/**/*.dart"])
    max_features: int = MAX_FEATURES
    max_context_chars: int = 60_000


@register("step", "agent.implement_spec")
class ImplementSpec(Step):
    """One LLM call and one commit per feature. The loop lives here, not in the YAML."""

    Params = ImplementParams
    needs = ("llm",)

    def run(self, ctx: StepContext, p: ImplementParams) -> StepResult:
        if len(p.features) > p.max_features:
            return StepResult.failed(f"plan has {len(p.features)} features, budget is {p.max_features}")
        done: list[str] = []
        for feature in p.features:
            files = collect_files(ctx.repo_dir, [], p.context_globs, p.max_context_chars)
            prompt = (f"TASK: implement\nAPP: {ctx.job.name}\nFEATURE: {feature.id}\n"
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
