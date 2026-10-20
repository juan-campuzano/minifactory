"""Declarative workflow: schema, loading and *fail-fast* validation.

Everything that can be checked without running anything is checked here: unknown
plugins, typos in step params, missing providers, `when` syntax, references to steps
that run later.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import registry
from .errors import WorkflowError

PROVIDER_KINDS = ("scm", "llm", "secrets")


class PluginRef(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    use: str
    with_: dict[str, Any] = Field(default_factory=dict, alias="with")


class StepSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    id: str
    use: str
    with_: dict[str, Any] = Field(default_factory=dict, alias="with")
    when: str | None = None
    on_fail: Literal["fail", "discard", "continue"] = "fail"
    blocking: bool = True  # False: a failure is recorded as a note and never stops the job


class RouteSpec(BaseModel):
    """Makes a workflow reachable from free text (`factory ask`). Without it, it is not."""

    model_config = ConfigDict(extra="forbid")
    description: str
    not_for: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    needs: str = ""  # what a request must contain for this workflow to start (judged by the router)
    intake: str  # name of a registered `intake` plugin that drafts the Job from the text
    # choose: the user picks where results go (new projects). fixed: the workflow delivers to its own target
    # (e.g. a pull request on the repository being changed) and `--output` does not apply.
    delivery: Literal["choose", "fixed"] = "choose"


SCHEMA_VERSION = 1


class WorkflowSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = SCHEMA_VERSION  # bump when the YAML format changes incompatibly
    name: str
    route: RouteSpec | None = None
    vars: dict[str, Any] = Field(default_factory=dict)
    source: PluginRef
    executor: PluginRef = PluginRef(use="local")
    providers: dict[str, PluginRef] = Field(default_factory=dict)
    steps: list[StepSpec]


def load_workflow(path: str | Path) -> WorkflowSpec:
    try:
        data = yaml.safe_load(Path(path).read_text())
        spec = WorkflowSpec.model_validate(data)
    except (OSError, yaml.YAMLError, ValidationError) as e:
        raise WorkflowError(f"cannot load workflow {path}: {e}") from None
    validate_spec(spec)
    return spec


def _is_templated(value: Any) -> bool:
    return isinstance(value, str) and "${" in value


def _check_params(step: StepSpec, cls: Any) -> None:
    try:
        cls.Params.model_validate(step.with_)
    except ValidationError as e:
        bad = [
            err
            for err in e.errors()
            if err["type"] == "missing" or not _is_templated(step.with_.get(err["loc"][0]))
        ]
        if bad:
            detail = "; ".join(f"{'.'.join(map(str, b['loc']))}: {b['msg']}" for b in bad)
            raise WorkflowError(f"step '{step.id}' (use: {step.use}): {detail}") from None


def validate_spec(spec: WorkflowSpec) -> None:
    for kind in spec.providers:
        if kind not in PROVIDER_KINDS:
            raise WorkflowError(f"unknown provider '{kind}' (expected one of {PROVIDER_KINDS})")
        registry.get(kind, spec.providers[kind].use)
    if spec.route:
        registry.get("intake", spec.route.intake)
    registry.get("source", spec.source.use)
    registry.get("executor", spec.executor.use)

    seen: list[str] = []
    for step in spec.steps:
        if step.id in seen:
            raise WorkflowError(f"duplicate step id '{step.id}'")
        cls = registry.get("step", step.use)
        for need in cls.needs:
            if need not in spec.providers:
                raise WorkflowError(
                    f"step '{step.id}' needs the '{need}' provider but the workflow defines none"
                )
        _check_params(step, cls)
        if step.when:
            try:
                ast.parse(step.when, mode="eval")
            except SyntaxError as e:
                raise WorkflowError(f"step '{step.id}': invalid when '{step.when}': {e.msg}") from None
        text = (step.when or "") + json.dumps(step.with_)
        for ref in re.findall(r"\bsteps\.(\w+)", text):
            if ref not in seen:
                raise WorkflowError(
                    f"step '{step.id}' refers to steps.{ref}, which does not run before it"
                )
        seen.append(step.id)
