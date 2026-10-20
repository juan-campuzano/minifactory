"""Generic, language-agnostic steps. `shell.run` is the workhorse: baseline gates, builds
and coverage phases are all just commands with different on_fail / blocking policies."""

from __future__ import annotations

from factory.core.context import Step, StepContext, StrictParams
from factory.core.models import StepResult
from factory.core.registry import register

from .util import run_shell, safe_path


class ShellParams(StrictParams):
    cmd: str
    timeout: int = 120


@register("step", "shell.run")
class ShellRun(Step):
    Params = ShellParams

    def run(self, ctx: StepContext, p: ShellParams) -> StepResult:
        rc, out = run_shell(p.cmd, ctx.repo_dir, p.timeout)
        outputs = {"rc": rc, "output": out[-4000:]}
        if rc == 0:
            return StepResult(outputs=outputs, message="ok")
        last = out.splitlines()[-1] if out else f"exit code {rc}"
        return StepResult(status="failed", outputs=outputs, message=last)


class SetKeyParams(StrictParams):
    file: str
    key: str
    value: str


@register("step", "file.set_key")
class SetKey(Step):
    """A deterministic transform (stand-in for your Gradle scaffold upgrade)."""

    Params = SetKeyParams

    def run(self, ctx: StepContext, p: SetKeyParams) -> StepResult:
        path = safe_path(ctx.repo_dir, p.file)
        lines, found = path.read_text().splitlines(), False
        for i, line in enumerate(lines):
            if line.startswith(p.key + "="):
                lines[i], found = f"{p.key}={p.value}", True
        if not found:
            lines.append(f"{p.key}={p.value}")
        path.write_text("\n".join(lines) + "\n")
        return StepResult.ok(f"{p.key}={p.value}")
