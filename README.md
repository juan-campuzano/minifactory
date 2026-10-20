# minifactory

> Workflows live in a **workspace** (a folder with `factory.yaml` and `workflows/`), not in the package: `factory init`
> creates one, `factory workflows list|copy` gives you the packaged templates. Relative paths inside a workflow
> (`specs/`, `output/`...) resolve from the workspace root, wherever you run `factory` from inside it.

A tiny software factory you can run on your laptop: a small **core engine** that runs
**declarative workflows** made of **plugin steps**, with everything environment-specific
behind **ports**.

```
┌──────────────── core (src/factory/core) ────────────────┐
│ engine · workflow validation · registry · events · expr │   knows nothing about
└───────────────────────────┬─────────────────────────────┘   Java, Git hosts or LLMs
        ports: SCM · LLM · Secrets · TargetSource · Executor
                            │
┌───────────── plugins (src/factory/plugins/builtin) ─────┐
│ local-git · scripted/openai LLM · env secrets · catalog │
│ shell.run · file.set_key · agent.repair_build · ...     │
└─────────────────────────────────────────────────────────┘
```

The rule that keeps it from becoming spaghetti: **the core never imports a plugin**;
plugins register themselves.

## Try it: build Flutter apps from specs

```bash
pip install -e ".[dev,aws]"          # from a clone; `aws` = boto3, only for the Bedrock LLM
factory init my-factory && cd my-factory          # a workspace: factory.yaml + workflows/
factory workflows copy flutter-app-factory        # templates ship with the package
factory validate flutter-app-factory
factory run flutter-app-factory                   # 4 specs in specs/; rm -rf demo-flutter to re-run
```

One job per spec in `specs/`: guard → `scm.init_repo` → `flutter.create` → `agent.plan_app` →
`agent.implement_spec` → analyze/test gates → repair loop → non-blocking coverage → PR. By default it uses a
deterministic fake `flutter` and canned LLM replies (`fixtures/flutter/`), so it needs no SDK or tokens;
`FACTORY_FLUTTER=real` runs the real binary.

| spec | what it exercises |
|---|---|
| `todo_app` | happy path |
| `counter_needs_repair` | first attempt uses a removed widget; analyze goes red; repair loop fixes it |
| `notes_low_coverage` | coverage below 80% never blocks the PR, it annotates it |
| `bad_spec` | plan is not valid JSON → job fails at `plan`, nothing is built |

Agents working on this repo: read `AGENTS.md`. Writing a plugin: `docs/plugins.md`.

## Describe what you need (`factory ask`)

```bash
export TYPESAFE_API_KEY=...        # Jev routes the request; AWS credentials for the Bedrock LLM
factory ask "quiero una app para llevar mis gastos" --dry-run   # picks the workflow, drafts the spec, runs nothing
factory ask "quiero una app para llevar mis gastos"             # same, then asks before running
```

Workflows opt in with a `route:` block (see the `flutter-app-factory-bedrock` template: `factory workflows copy flutter-app-factory-bedrock`). Details in `AGENTS.md`.

## Try it: the Java migration demo (transform existing repos)

```bash
factory init my-factory && cd my-factory && factory workflows copy java-migration-demo
factory demo-init                                   # 6 toy repos + catalog in ./demo
factory validate java-migration-demo              # fail-fast checks, runs nothing
factory run java-migration-demo                   # run it
factory run java-migration-demo --quiet           # 2nd run: guard dedupes
pytest
```

The demo is a miniature of your codemod worker, one toy repo per path:

| repo | what it exercises |
|---|---|
| `svc-clean-ok` | deterministic transform, green build, no repair |
| `svc-other-ok` | LLM transform (other branch of `when`), non-blocking coverage failure → note in PR |
| `svc-needs-repair` | build goes red, repair loop fixes it |
| `svc-broken-baseline` | baseline gate fails → job **discarded**, nothing changed |
| `svc-unfixable` | repair loop hits its anti-loop budget → job **failed** |
| `svc-modern` | filtered out by the source |

Artifacts per job live in `.factory/runs/<workflow>/<job>/` (`state.json`, `result.json`,
the cloned `work/` dir). `events.jsonl` has every step and LLM call.
`factory run ... --resume` restarts from the first step that did not finish `ok`.

## The workflow format

Deliberately small: sequence, `when`, `on_fail: fail|discard|continue`, `blocking: false`,
and `${...}` templating over `job`, `steps`, `vars`, `env`. No loops, no calls, no
arithmetic. If you want that, write a step in Python.

Everything checkable is checked at load time: unknown plugins, typos in params, missing
providers, bad `when` syntax, references to steps that run later.

## Add your own step (no core changes)

```python
# my_plugin.py
from factory.core.context import Step, StrictParams
from factory.core.models import StepResult
from factory.core.registry import register

class Params(StrictParams):
    message: str

@register("step", "demo.hello")
class Hello(Step):
    Params = Params
    def run(self, ctx, p):
        return StepResult.ok(f"hello {ctx.job.name}: {p.message}")
```

```bash
factory run my-workflow.yaml --plugin my_plugin
```

Installed packages can instead expose the `factory.plugins` entry point (see
`pyproject.toml`) and are discovered automatically.

## From toy to your real codemod

Each is one new plugin implementing an existing port:

| codemod today | port | plugin to write |
|---|---|---|
| Neptune Gremlin query | `source` | `neptune` |
| Azure DevOps clone/PR/work item | `scm` | `azure-devops` (later `github`) |
| LiteLLM gateway | `llm` | already there: `openai` with `base_url` |
| Cross-account STS assume-role | `secrets` | `aws-sts-secrets` |
| AWS Batch fan-out | `executor` | `aws-batch` (submit the job id, worker runs `run_job`) |
| Gradle `updateCleanArchitecture`, `validateStructure` | `step` | `gradle.*` steps (or just `shell.run`) |
| Copilot CLI agent | `step` | `agent.copilot_*` (same budgets as `agent.repair_build`) |

Next things worth adding once a *second* system needs them (not before): a persistent
state store instead of local JSON, step timeouts/retries as engine policies, per-job
token/cost aggregation from `llm_call` events.
