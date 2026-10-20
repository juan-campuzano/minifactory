# Writing plugins

A plugin is a Python class registered under a **kind** and a **name**. Nothing else to edit.
Load it with `minifactory run wf.yaml --plugin my_module`, or ship a package exposing the `minifactory.plugins`
entry point (see `pyproject.toml`).

| kind | you implement | used from YAML as |
|---|---|---|
| `step` | `Step` subclass with `Params` and `run(ctx, params) -> StepResult` | `steps: - use: x.y` |
| `scm` | `default_branch, clone, branch_exists, open_prs, push_and_open_pr` | `providers.scm.use` |
| `llm` | `complete(system, prompt) -> str` | `providers.llm.use` |
| `secrets` | `get(name) -> str` | `providers.secrets.use` |
| `source` | `jobs() -> list[Job]` | `source.use` |
| `executor` | `run(jobs, fn) -> list[JobResult]` | `executor.use` |
| `router` | `choose(request, candidates) -> Decision` | `minifactory ask --router NAME` |
| `intake` | `build(request, llm) -> Job` | `route.intake` in a workflow |

Constructor arguments of providers/sources/executors come from the `with:` block. A provider whose `__init__`
takes `secrets` gets the secrets provider injected.

## 1. A step (`examples/hello_plugin.py`)
```python
@register("step", "demo.hello")
class Hello(Step):
    Params = Params          # StrictParams: typos in YAML fail at load time
    needs = ()               # e.g. ("llm",): validated before anything runs
    def run(self, ctx, p):
        return StepResult.ok("hello", text=p.message)   # outputs feed later steps
```
Return `StepResult.failed(msg)` for expected failures, `StepResult.discarded(msg)` to stop the job on purpose.
Put text in `notes=[...]` to surface it in the PR description. `ctx.emit("my_event", ...)` writes to `events.jsonl`.

## 2. A source (what to work on)
```python
@register("source", "static-list")
class Names:
    def __init__(self, names: list[str]): self.names = names
    def jobs(self): return [Job(id=n, name=n, attrs={}) for n in self.names]
```
Real example: `app-specs` in `providers_misc.py` (one job per YAML spec).

## 3. A secrets provider
```python
@register("secrets", "file")
class FileSecrets:
    def __init__(self, dir: str): self.dir = Path(dir)
    def get(self, name: str) -> str: return (self.dir / name).read_text().strip()
```
Your cross-account STS assume-role logic belongs in a provider like this one.

## 4. An LLM or SCM provider
Copy `FixtureLLM` / `OpenAICompatLLM` (`providers_llm.py`) or `LocalGit` (`providers_scm.py`) and swap the transport.
Optional capabilities (like `LocalGit.init_repo`) are plain extra methods, checked with `getattr` by the step that needs them.

## Checklist
- Params are `StrictParams`; unknown keys must fail.
- Treat anything an LLM returns as untrusted (validate, confine paths, bound loops).
- Add a test using `fixture`/`scripted` LLM; no network in tests.
