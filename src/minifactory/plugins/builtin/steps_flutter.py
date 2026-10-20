"""Flutter steps. They call `flutter_tool`, so the same workflow runs against the real SDK
(FACTORY_FLUTTER=real) or the deterministic fake (default)."""

from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path
from typing import Literal

from minifactory.core.context import Step, StepContext, StrictParams
from minifactory.core.models import StepResult
from minifactory.core.registry import register

from .util import commit_all, run_shell

Tool = Literal["auto", "real", "fake"]


def _run(ctx: StepContext, args: str, timeout: int, tool: Tool | None) -> tuple[int, str]:
    """`tool=None` defers to $FACTORY_FLUTTER, then to the real SDK (see flutter_tool)."""
    flag = f" --tool {tool}" if tool else ""
    cmd = f"{shlex.quote(sys.executable)} -m minifactory.plugins.builtin.flutter_tool{flag} {args}"
    return run_shell(cmd, ctx.repo_dir, timeout)


def _result(rc: int, out: str, **outputs: object) -> StepResult:
    outputs |= {"rc": rc, "output": out[-4000:]}
    if rc == 0:
        return StepResult(outputs=outputs, message="ok")
    return StepResult(status="failed", outputs=outputs,
                      message=(out.splitlines() or [f"exit code {rc}"])[-1])


class CreateParams(StrictParams):
    org: str = "com.example"
    timeout: int = 300
    tool: Tool | None = None


@register("step", "flutter.create")
class FlutterCreate(Step):
    """`flutter create` inside the already-initialised repo. Project name = job name."""

    Params = CreateParams

    def run(self, ctx: StepContext, p: CreateParams) -> StepResult:
        name = re.sub(r"\W", "_", ctx.job.name).lower()
        rc, out = _run(ctx, f"create --project-name {shlex.quote(name)} --org {shlex.quote(p.org)} .",
                       p.timeout, p.tool)
        if rc == 0:
            commit_all(ctx.repo_dir, "chore: flutter create")
        return _result(rc, out, project=name)


class AnalyzeParams(StrictParams):
    timeout: int = 300
    tool: Tool | None = None


@register("step", "flutter.analyze")
class FlutterAnalyze(Step):
    Params = AnalyzeParams

    def run(self, ctx: StepContext, p: AnalyzeParams) -> StepResult:
        return _result(*_run(ctx, "analyze", p.timeout, p.tool))


class RunTestsParams(StrictParams):
    coverage: bool = False
    min_coverage: float | None = None  # percent of lines; below it the step fails
    timeout: int = 600
    tool: Tool | None = None
    paths: list[str] = []  # run only these test files
    expect_failure: bool = False  # the 'bug is reproduced' gate: tests must fail, and for the right reason


def _line_coverage(lcov: Path) -> float | None:
    if not lcov.is_file():
        return None
    found = hit = 0
    for line in lcov.read_text().splitlines():
        if line.startswith("LF:"):
            found += int(line[3:])
        elif line.startswith("LH:"):
            hit += int(line[3:])
    return round(100 * hit / found, 1) if found else None


@register("step", "flutter.test")
class FlutterTest(Step):
    """`flutter test`, optionally with coverage and a minimum line-coverage threshold
    (read from coverage/lcov.info, which real Flutter and the fake both write)."""

    Params = RunTestsParams

    def run(self, ctx: StepContext, p: RunTestsParams) -> StepResult:
        with_coverage = p.coverage or p.min_coverage is not None
        args = ("test --coverage" if with_coverage else "test") + "".join(f" {shlex.quote(x)}" for x in p.paths)
        rc, out = _run(ctx, args, p.timeout, p.tool)
        if p.expect_failure:
            if rc in (124, 127):
                return StepResult(status="failed", outputs={"rc": rc, "output": out[-4000:]},
                                  message=f"could not run flutter: {out[-200:]}")
            if rc == 0:
                return StepResult(status="failed", outputs={"rc": rc, "output": out[-4000:]},
                                  message="expected the tests to fail, but they passed")
            if "Compilation failed" in out or "Failed to load" in out:  # red, but not because of the bug
                return StepResult(status="failed", outputs={"rc": rc, "output": out[-4000:]},
                                  message="the test does not compile, so it proves nothing")
            return StepResult(outputs={"rc": rc, "output": out[-4000:]}, message="failed as expected")
        result = _result(rc, out)
        if rc != 0 or not with_coverage:
            return result
        pct = _line_coverage(ctx.repo_dir / "coverage" / "lcov.info")
        result.outputs["coverage"] = pct
        if p.min_coverage is not None and (pct is None or pct < p.min_coverage):
            return StepResult(status="failed", outputs=result.outputs,
                              message=f"coverage {pct}% is below {p.min_coverage}%")
        return result
