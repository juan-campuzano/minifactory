# minifactory

A tiny, pluggable **software factory**. You describe what you need, a **workflow** does the work, and every
step an AI agent takes is fenced in by deterministic checks, budgets and a human-reviewable result.

- **Declarative workflows**: YAML made of plugin steps, validated before anything runs.
- **Agents on a leash**: the LLM is a step, never the boss. Its output is untrusted, bounded by budgets and
  followed by real gates (a compiler, a test run, a diff-size limit).
- **Everything environment-specific sits behind ports** (git host, LLM, secrets, job source, executor), so
  swapping GitHub for another host or Bedrock for another model is a one-line change.
- **Ask in plain language**: `factory ask "..."` picks the right workflow, drafts its input, and asks before it runs.

> Status: **alpha**. The engine, the CLI and three example workflows work and are tested; see
> [Limitations](#limitations) for what has and has not been verified.

```
┌──────────────── core (src/factory/core) ────────────────┐
│ engine · workflow validation · registry · events · expr │   knows nothing about
└───────────────────────────┬─────────────────────────────┘   languages, git hosts or LLMs
   ports: scm · llm · secrets · source · executor · router · intake
                            │
┌───────────── plugins (src/factory/plugins/builtin) ─────┐
│ github · local-git · bedrock · openai · jev router      │
│ shell.run · agent.edit · flutter.* · scm.open_pr · ...  │
└─────────────────────────────────────────────────────────┘
```

The rule that keeps it from becoming spaghetti: **the core never imports a plugin**; plugins register themselves.

## Install

```bash
git clone https://github.com/juan-campuzano/minifactory && cd minifactory
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # add ",aws" for the Amazon Bedrock LLM (installs boto3)
```

Python 3.11+. Workflows live in a **workspace**, not in the package (see below).

## Quick start (offline, no keys, no SDK)

```bash
factory init my-factory && cd my-factory       # a workspace: factory.yaml + workflows/
factory workflows list                         # templates that ship with the package
factory workflows copy flutter-app-factory     # copies the workflow and its sample inputs
factory validate flutter-app-factory           # fail-fast checks, runs nothing
factory run flutter-app-factory                # runs 4 sample jobs with canned LLM replies
```

This example factory turns an app spec into a project: plan, implement, build/test gates, an automatic repair
loop, a non-blocking coverage check, then delivery. The offline run uses a *simulated* `flutter` and canned LLM
replies, so what it produces is not a real project. It exists to show every path the engine can take:

| sample job | what it exercises |
|---|---|
| `todo_app` | happy path |
| `counter_needs_repair` | the first attempt breaks the build; the repair loop fixes it |
| `notes_low_coverage` | coverage below the threshold never blocks delivery, it annotates it |
| `bad_spec` | the plan is not valid JSON, so the job fails early and nothing is built |

Each job leaves `state.json`, `result.json` and its working copy in `.factory/runs/<workflow>/<job>/`;
`events.jsonl` records every step and LLM call (tokens and cost when the provider reports them).
`factory run ... --resume` restarts from the first step that did not finish `ok`.

## Workspaces

Code ships in the package; your content lives in a workspace, found like git (nearest `factory.yaml` going up from
the current directory, else `~/.config/minifactory`):

```
my-factory/
  factory.yaml      optional settings: runs_dir, output_dir, router, threshold, plugins
  workflows/        your workflows, the ones `factory ask` can choose from
  ...               anything your workflows reference (specs/, fixtures/...), relative to this folder
```

Relative paths inside a workflow resolve from the workspace root, wherever you run `factory` inside it.
Command-line flags override `factory.yaml`, which overrides the defaults.

## Example workflows (templates)

Copy one into your workspace with `factory workflows copy NAME`; only copied workflows are routable by `ask`.

| template | what it does | needs |
|---|---|---|
| `flutter-app-factory` | the offline demo above | nothing |
| `flutter-app-factory-bedrock` | creates a **new** Flutter app from a one-line request, sized to the request ("minimal" means few features) | AWS credentials (Bedrock), Flutter SDK |
| `fix-bug` | fixes a bug in an **existing** GitHub repo: reproduces it with a failing test, fixes it minimally, opens a PR | `gh auth login`, AWS credentials, Flutter SDK |
| `java-migration-demo` | a batch transform over toy repos: deterministic branch vs LLM branch, baseline gate, repair loop | nothing |

## Describe what you need: `factory ask`

```bash
export TYPESAFE_API_KEY=...       # for the default router (Jev); `--router keyword` works offline
factory ask "a simple app to track my expenses" --dry-run   # picks a workflow, drafts its input, runs nothing
factory ask "a simple app to track my expenses"             # same, then asks before running
```

1. A **router** plugin chooses among the workflows that declare a `route:` block, and says how confident it is.
2. Policy lives in code, not in the model: with `--yes` it only acts when the router is confident, the request is
   actionable and a workflow fits; otherwise it exits without doing anything.
3. The workflow's **intake** plugin drafts its input from your text (the text is treated as data, the result is
   validated), and you confirm before anything runs.
4. **Where results go** is your choice for new projects: `--output local` (a plain git folder) or
   `--output github` (a new private repo plus a pull request; `--public` to change that).

## Fix a bug in an existing repo

```bash
factory workflows copy fix-bug
factory ask "the counter goes up by 2 instead of 1 in acme/todo_app" --dry-run
```

`fix-bug` clones the repo with `gh`, requires the repo to analyse cleanly, selects the relevant files, writes a test
that reproduces the bug (and stops without changing anything if that test does not fail), fixes it with an
exact-match patch, re-runs the checks, enforces a size limit on the change, and opens a pull request.
It never touches the default branch.

## Design principles

- **Untrusted agent output.** Edits are parsed strictly: a `PATCH` must match exactly once or nothing is written;
  paths cannot escape the repo; plans are validated with pydantic; the Bedrock provider rejects a reply cut off by the token limit.
- **Bounded loops.** Repair attempts, unproductive attempts, features per plan and context size all have budgets.
- **Deterministic gates after every agent step.** `on_fail: discard` stops a job without changing anything;
  `blocking: false` lets enrichment steps annotate a result without stopping it.
- **Proposals, not pushes.** Changes to existing repos arrive as a pull request on a new branch.
- **No silent fakes.** The simulated `flutter` is opt-in (`tool: fake` or `FACTORY_FLUTTER=fake`); by default the
  real SDK is required and a missing one is an error.

## The workflow format

Deliberately small: sequence, `when`, `on_fail: fail|discard|continue`, `blocking: false`, and `${...}` templating
over `job`, `steps`, `vars` and `env`. No loops, no calls, no arithmetic: if you need that, write a step in Python.
Everything checkable is checked at load time: unknown plugins, typos in parameters, missing providers, bad `when`
syntax, references to steps that run later.

## Write a plugin

No core changes needed. A step is a class with typed parameters:

```python
# my_plugin.py
from factory.core.context import Step, StrictParams
from factory.core.models import StepResult
from factory.core.registry import register

class Params(StrictParams):          # unknown keys in the YAML are errors
    message: str

@register("step", "demo.hello")
class Hello(Step):
    Params = Params
    def run(self, ctx, p):
        return StepResult.ok(f"hello {ctx.job.name}: {p.message}")
```

```bash
factory run my-workflow --plugin my_plugin
```

Installed packages can instead expose the `factory.plugins` entry point and are discovered automatically.
Plugin kinds: `step`, `source`, `executor`, `scm`, `llm`, `secrets`, `router`, `intake`. Built in:

| kind | built in |
|---|---|
| `scm` | `github` (via the `gh` CLI), `local-git`, `local-dir` |
| `llm` | `bedrock`, `openai` (any OpenAI-compatible endpoint), `fixture`, `scripted` |
| `router` | `jev` (TypeSafe), `keyword` |
| `intake` | `app-spec`, `repo-task` |
| `source` | `app-specs`, `repo-tasks`, `catalog`, `static` |
| `executor` | `local`, `threads` |
| `secrets` | `env` |

See [`docs/plugins.md`](docs/plugins.md) for each kind's interface, and [`AGENTS.md`](AGENTS.md) if you are an AI
coding agent (or work with one) on this repo.

## Limitations

- **Alpha.** Only Python 3.11 and 3.13 are tested in CI.
- The example workflows target Flutter/Dart. Other stacks need their own steps (or `shell.run`).
- The real-model runs were small: a one-line app, and a seeded one-line bug in a small repo. Larger apps, where
  features must agree with each other, are not solved: expect failures there.
- The `github` provider has been exercised against a fake `gh` in tests and has created repos in manual runs; the
  existing-repo flow has only been run against a local git remote, not against a real GitHub repository.
- No built-in retry or timeout policy at the engine level, and no persistent state store beyond local JSON files.

## Development

```bash
pip install -e ".[dev]"
ruff check src tests examples
pytest -q            # no network, credentials or Flutter SDK needed
```

## License

MIT, see [`LICENSE`](LICENSE).
