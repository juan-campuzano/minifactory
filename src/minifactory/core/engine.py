"""The engine: runs one job through the workflow's steps.

It owns the cross-cutting concerns so steps don't have to: `when`, `on_fail`,
`blocking`, templating, state persistence + resume, events, LLM metering.
"""

from __future__ import annotations

import inspect
import json
import shlex
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from . import registry
from .context import StepContext
from .events import EventBus, JsonlSink
from .expr import NS, evaluate, render
from .models import Job, JobResult, StepRecord, StepResult
from .workflow import PluginRef, WorkflowSpec


class _MeteredLLM:
    """Wraps the LLM port so every call becomes an event (cost/latency dashboards).

    Providers may also implement `complete_ex(system, prompt) -> (text, usage)` where usage
    has `input_tokens`, `output_tokens` and optionally `cost_usd`; those go into the event."""

    def __init__(self, inner: Any, emit: Any):
        self._inner, self._emit = inner, emit

    def complete(self, system: str, prompt: str) -> str:
        t0 = time.monotonic()
        usage: dict[str, Any] = {}
        if hasattr(self._inner, "complete_ex"):
            out, usage = self._inner.complete_ex(system, prompt)
        else:
            out = self._inner.complete(system, prompt)
        self._emit(
            "llm_call",
            chars_in=len(system) + len(prompt),
            chars_out=len(out),
            duration_s=round(time.monotonic() - t0, 3),
            **usage,
        )
        return out


class Engine:
    def __init__(self, spec: WorkflowSpec, runs_dir: str | Path = ".minifactory/runs",
                 bus: EventBus | None = None):
        self.spec = spec
        self.runs_dir = Path(runs_dir)
        self.bus = bus or EventBus()
        self.bus.subscribe(JsonlSink(self.runs_dir / spec.name / "events.jsonl"))

        self.secrets = self._build("secrets", spec.providers.get("secrets") or PluginRef(use="env"))
        self.scm = self._build("scm", spec.providers["scm"]) if "scm" in spec.providers else None
        self.llm = self._build("llm", spec.providers["llm"]) if "llm" in spec.providers else None
        self.source = self._build("source", spec.source)
        self.executor = self._build("executor", spec.executor)
        self.runner = self._build("runner", spec.runner)

    # -- construction -------------------------------------------------------------
    def _build(self, kind: str, ref: PluginRef) -> Any:
        cls = registry.get(kind, ref.use)
        kwargs = dict(ref.with_)
        if kind != "secrets" and "secrets" in inspect.signature(cls).parameters:
            kwargs["secrets"] = self.secrets  # e.g. the LLM provider reads its API key
        return cls(**kwargs)

    def _env(self, job: Job, records: list[StepRecord]) -> dict[str, Any]:
        steps = {
            r.id: {"status": r.status, "message": r.message, "outputs": r.outputs}
            for r in records
        }
        return {
            "job": NS({"id": job.id, "name": job.name, **job.attrs}),
            "steps": NS(steps),
            "vars": NS(self.spec.vars),
            "env": NS({"python": shlex.quote(sys.executable)}),
        }

    # -- running ------------------------------------------------------------------
    def run_job(self, job: Job, resume: bool = False) -> JobResult:
        run_dir = self.runs_dir / self.spec.name / job.id
        prior: dict[str, StepRecord] = {}
        state_file = run_dir / "state.json"
        if resume and state_file.exists():
            prior = {r["id"]: StepRecord(**r) for r in json.loads(state_file.read_text())["steps"]}
        elif run_dir.exists():
            shutil.rmtree(run_dir)
        (run_dir / "work").mkdir(parents=True, exist_ok=True)

        def emit(type: str, **data: Any) -> None:
            self.bus.emit(type, job=job.id, **data)

        ctx = StepContext(
            job=job,
            work_dir=run_dir / "work",
            scm=self.scm,
            llm=_MeteredLLM(self.llm, emit) if self.llm else None,
            secrets=self.secrets,
            emit=emit,
            runner=self.runner,
        )
        records: list[StepRecord] = []
        artifacts = []
        outcome, reason = "succeeded", ""
        emit("job_started")

        for step in self.spec.steps:
            env = self._env(job, records)
            t0 = time.monotonic()

            previous = prior.get(step.id)
            if previous and previous.status == "ok":  # resume: restore, don't re-run
                result, resumed = previous, True
            else:
                resumed = False
                if step.when and not evaluate(step.when, env):
                    result = StepResult(status="skipped", message=f"when: {step.when}")
                else:
                    emit("step_started", step=step.id)
                    result = self._execute(step, ctx, env)

            record = StepRecord(
                id=step.id, duration_s=round(time.monotonic() - t0, 3),
                **result.model_dump(exclude={"id", "duration_s"}),
            )
            records.append(record)
            ctx.outputs[step.id] = record.outputs
            ctx.notes.extend(record.notes)
            artifacts.extend(record.artifacts)
            state_file.write_text(json.dumps({"steps": [r.model_dump() for r in records]}, indent=2))
            emit("step_finished", step=step.id, status=record.status,
                 message=record.message, duration_s=record.duration_s, resumed=resumed)

            if record.status == "discarded":
                outcome, reason = "discarded", f"{step.id}: {record.message}"
                break
            if record.status == "failed":
                first_line = (record.message.splitlines() or [""])[0]
                if not step.blocking:
                    ctx.notes.append(f"non-blocking step '{step.id}' failed: {first_line}")
                elif step.on_fail == "discard":
                    outcome, reason = "discarded", f"{step.id}: {first_line}"
                    break
                elif step.on_fail == "fail":
                    outcome, reason = "failed", f"{step.id}: {first_line}"
                    break
                # on_fail == "continue": keep going, later steps can inspect steps.<id>.status

        result_obj = JobResult(job_id=job.id, outcome=outcome, reason=reason, steps=records,
                               artifacts=artifacts, notes=ctx.notes)
        (run_dir / "result.json").write_text(result_obj.model_dump_json(indent=2))
        emit("job_finished", outcome=outcome, reason=reason)
        return result_obj

    def _execute(self, step: Any, ctx: StepContext, env: dict[str, Any]) -> StepResult:
        try:
            cls = registry.get("step", step.use)
            params = cls.Params.model_validate(render(step.with_, env))
            return cls().run(ctx, params)
        except Exception as e:  # a crashing plugin must not take the factory down
            return StepResult.failed(f"{type(e).__name__}: {e}")
