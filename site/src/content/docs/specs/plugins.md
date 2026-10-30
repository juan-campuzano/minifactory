---
title: Writing Plugins
description: How to extend minifactory with custom steps, providers, sources, routers, intakes, and runners.
---

The core engine never imports plugins directly; plugins register themselves with `@register(kind, name)`. Load custom plugins via `--plugin my_module`, `plugins: [my_module]` in `minifactory.yaml`, or the `minifactory.plugins` Python package entry point.

## Plugin Kinds

| Kind | Interface to Implement | Used in YAML as |
|---|---|---|
| `step` | `Step` subclass with `Params` (`StrictParams`) and `run(ctx, params) -> StepResult` | `steps: - use: x.y` |
| `scm` | `default_branch, clone, branch_exists, open_prs, push_and_open_pr` (+ optional `init_repo`, `pr_view`, `pr_diff`, `pr_comment`) | `providers.scm.use` |
| `llm` | `complete(system, prompt) -> str` (or `complete_ex(system, prompt) -> (str, usage)`) | `providers.llm.use` / `llms.<role>.use` |
| `secrets` | `get(name) -> str` | `providers.secrets.use` |
| `source` | `jobs() -> list[Job]` | `source.use` |
| `executor` | `run(jobs, fn) -> list[JobResult]` | `executor.use` |
| `router` | `choose(request, candidates) -> Decision` | `minifactory ask --router NAME` |
| `intake` | `build(request, llm) -> Job` | `route.intake` |
| `runner` | `run(cmd, cwd, timeout) -> (rc, output)` | `runner.use` |

## Example: Writing a Custom Step

```python
from minifactory.core.context import Step, StepContext, StrictParams
from minifactory.core.models import StepResult
from minifactory.core.registry import register


class HelloParams(StrictParams):
    message: str


@register("step", "demo.hello")
class Hello(Step):
    """Greet the current job and expose the greeting as an output."""

    Params = HelloParams
    needs = ()  # e.g. ("llm",) or ("scm",)

    def run(self, ctx: StepContext, p: HelloParams) -> StepResult:
        text = f"hello {ctx.job.name}: {p.message}"
        return StepResult.ok(text, greeting=text)
```

## Hard Rules for Plugin Authors

1. **Always subclass `StrictParams`** so unknown YAML keys fail at validation time.
2. **Never raise exceptions for expected failures**: return `StepResult.failed("reason")` or `StepResult.discarded("reason")`.
3. **Never call `subprocess` directly inside a step**: use `run_cmd(ctx, cmd, timeout)` so execution goes through `ctx.runner` and its environment/isolation policy.
4. **Give every plugin class its own docstring**: `minifactory plugins --schema` and `create-workflow` extract the class's own `__doc__` to build the catalog.
