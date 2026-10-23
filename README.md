<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/juan-campuzano/minifactory/main/assets/brand/png/minifactory-horizontal-dark.png">
    <img src="https://raw.githubusercontent.com/juan-campuzano/minifactory/main/assets/brand/png/minifactory-horizontal-light.png" alt="minifactory" width="420">
  </picture>
</p>

A tiny, pluggable **software factory**. You describe what you need, a **workflow** does the work, and every
step an AI agent takes is fenced in by deterministic checks, budgets and a human-reviewable result.

- **Declarative workflows**: YAML made of plugin steps, validated before anything runs.
- **Agents on a leash**: the LLM is a step, never the boss. Its output is untrusted, bounded by budgets and
  followed by real gates (a compiler, a test run, a diff-size limit).
- **Everything environment-specific sits behind ports** (git host, LLM, secrets, job source, executor), so
  swapping GitHub for another host or Bedrock for another model is a one-line change.
- **Ask in plain language**: `minifactory ask "..."` picks the right workflow, drafts its input, and asks before it runs.

> Status: **alpha**. The engine, the CLI and three example workflows work and are tested; see
> [Limitations](#limitations) for what has and has not been verified.

```
┌─ core (src/minifactory/core) ────────────────────────────────────┐
│ engine · workflow validation · registry · events · expressions   │
└──────────────────────────────────────────────────────────────────┘
  knows nothing about languages, git hosts or LLMs; those sit behind ports:
  scm · llm · secrets · source · executor · router · intake

┌─ plugins (src/minifactory/plugins/builtin) ──────────────────────┐
│ steps/      shell · agent · stack · flutter · scm · workflows    │
│ providers/  github · local-git · bedrock · openai · secrets      │
│ routing/    jev and keyword routers · intakes                    │
└──────────────────────────────────────────────────────────────────┘
```

The rule that keeps it from becoming spaghetti: **the core never imports a plugin**; plugins register themselves.

## Install

> **Pre-release.** `0.0.2a3` is an alpha: `pip` and `uv` skip pre-releases unless you ask, so a plain install still gets `0.0.1`.
> To try the alpha: `uv tool install --prerelease allow minifactory` or `pip install --pre minifactory`.

The easiest way to get the `minifactory` command is a tool installer, which keeps it isolated and on your `PATH`:

```bash
uv tool install minifactory            # or: pipx install minifactory
uv tool install "minifactory[aws]"     # + boto3, for the Amazon Bedrock LLM
```

Or with plain pip, ideally inside a virtual environment:

```bash
pip install minifactory
pip install "minifactory[aws]"
```

> **`minifactory: command not found` after `pip install`?** pip puts console scripts next to the Python it installed
> into, and that folder is often not on your `PATH` (typical with the python.org macOS installer, where it is
> `/Library/Frameworks/Python.framework/Versions/3.X/bin`). Use `uv tool install` / `pipx`, add that folder to `PATH`,
> or run `python3 -m minifactory ...`. Beware of zsh's `AUTO_CD`: if a folder called `minifactory` exists where you
> are, typing the bare word changes into it instead of reporting the missing command.

From source, for development:

```bash
git clone https://github.com/juan-campuzano/minifactory && cd minifactory
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,aws]"
```

Python 3.11+. Workflows live in a **workspace**, not in the package (see below).

## Tab completion

```bash
minifactory completion install      # shows what it will change and asks first
minifactory completion status       # installed / stale / missing
minifactory completion uninstall    # puts your rc file back exactly as it was
```

It cannot happen by itself at install time (neither `pip` nor `uv` runs anything), so it is one command. `install` detects your shell
(zsh, bash or fish; `--shell` to choose), writes the script under `~/.config/minifactory/completion/` and adds a **small marked block**
to your rc file (`~/.zshrc`, `~/.bashrc` or `~/.bash_profile`; fish needs no edit). It keeps a one-time backup, is safe to run twice, and
`--dry-run` prints everything without touching anything. `minifactory doctor` tells you if it is missing or out of date after an upgrade, and
`minifactory init` mentions it once in a terminal.

Tab completes commands and flags, and **the names that exist in your workspace**: your workflows (`minifactory run <Tab>`), the packaged
templates (`workflows copy <Tab>`), drafts waiting to be enabled (`workflows enable <Tab>`) and the routers (`ask --router <Tab>`). Start
typing a path (`./`, `workflows/`) and it completes `.yaml` files instead. It needs the `minifactory` command on your `PATH` (see Install).

Prefer to wire it yourself? `eval "$(minifactory completion show zsh)"` (or `bash`; for fish `minifactory completion show fish | source`).
Use `eval "$(...)"`, not `source <(...)`: macOS's bash 3.2 cannot source a process substitution. fish is generated by argcomplete but I have
not tested it.

## Check your setup: `minifactory doctor`

```bash
minifactory doctor                  # what is installed and configured: toolchains per stack, AWS, gh, router key
minifactory doctor fix-bug          # what THIS workflow needs: a missing requirement fails (exit code 1)
minifactory doctor --online         # also contacts AWS and GitHub to check the logins work
minifactory doctor --json           # for scripts and CI
```

A missing toolchain is only information until a workflow needs it. Secrets are reported as "set", never printed, and
nothing leaves your machine unless you pass `--online`.

## Quick start (offline, no keys, no SDK)

```bash
minifactory init my-factory && cd my-factory       # a workspace: minifactory.yaml + workflows/
minifactory workflows list                         # templates that ship with the package
minifactory workflows copy flutter-app-factory     # copies the workflow and its sample inputs
minifactory validate flutter-app-factory           # fail-fast checks, runs nothing
minifactory run flutter-app-factory                # runs 4 sample jobs with canned LLM replies
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

Each job leaves `state.json`, `result.json` and its working copy in `.minifactory/runs/<workflow>/<job>/`;
`events.jsonl` records every step and LLM call (tokens and cost when the provider reports them).
`minifactory run ... --resume` restarts from the first step that did not finish `ok`.

## Workspaces

Code ships in the package; your content lives in a workspace, found like git (nearest `minifactory.yaml` going up from
the current directory, else `~/.config/minifactory`):

```
my-factory/
  minifactory.yaml      optional settings: runs_dir, output_dir, router, threshold, plugins
  workflows/        your workflows, the ones `minifactory ask` can choose from
  ...               anything your workflows reference (specs/, fixtures/...), relative to this folder
```

Relative paths inside a workflow resolve from the workspace root, wherever you run `minifactory` inside it.
Command-line flags override `minifactory.yaml`, which overrides the defaults.

## Example workflows (templates)

Copy one into your workspace with `minifactory workflows copy NAME`; only copied workflows are routable by `ask`.

| template | what it does | needs |
|---|---|---|
| `flutter-app-factory` | the offline demo above | nothing |
| `app-factory` | creates a **new** project (an app, a CLI, a library) from a one-line request, in Python, Node, Java, Dart or Flutter, sized to the request | AWS credentials (Bedrock) and the stack's tools |
| `fix-bug` | fixes a bug in an **existing** GitHub repo (Python, Node or Flutter, detected from its files): reproduces it with a failing test, fixes it minimally, opens a PR | `gh auth login`, AWS credentials, the stack's tools |
| `add-feature` | adds a feature to an **existing** GitHub repo: implements it with tests, runs the repo's own analyze/test, repairs, opens a PR (never touches the default branch). Set `vars.stack` when the stack cannot be guessed (a pure Dart package: `dart`) | `gh auth login`, AWS credentials, the stack's tools |
| `review-pr` | reviews an **existing** pull request (`review PR 12 in owner/name` or its URL): an LLM reads the diff and posts ONE comment with validated findings. Never approves or merges; reviews each commit once; `vars.post: false` only writes the report | `gh auth login`, AWS credentials |
| `create-workflow` | drafts a **new workflow** from a plain-language goal, using only the steps and plugins that exist (see below) | AWS credentials (Bedrock) |
| `java-migration-demo` | a batch transform over toy repos: deterministic branch vs LLM branch, baseline gate, repair loop | nothing |

## Describe what you need: `minifactory ask`

```bash
export TYPESAFE_API_KEY=...       # for the default router (Jev); `--router keyword` works offline
minifactory ask "a simple app to track my expenses" --dry-run   # picks a workflow, drafts its input, runs nothing
minifactory ask "a simple app to track my expenses"             # same, then asks before running
```

1. A **router** plugin chooses among the workflows that declare a `route:` block, and says how confident it is.
2. Policy lives in code, not in the model: with `--yes` it only acts when the router is confident, the request is
   actionable and a workflow fits; otherwise it exits without doing anything.
3. The workflow's **intake** plugin drafts its input from your text (the text is treated as data, the result is
   validated), and you confirm before anything runs.
4. **Where results go** is your choice for new projects: `--output local` (a plain git folder) or
   `--output github` (a new private repo plus a pull request; `--public` to change that).

## As a conversation: `minifactory chat`
```
$ minifactory chat
you › review the latest pull request
  ...the router picks review-pr, but no PR was named...
  Add details to try again (empty to drop it): PR 7 in acme/app
  repo: acme/app · pr: 7      delivery → pull request on github.com/acme/app
  Run it? [y/N]
```
The same flow as `ask` (route, draft the input, show where it would deliver, ask before running), one request after another.
When something is missing it asks for it and retries with your answer added, instead of failing. `/workflows` lists what it can do,
`/help` the rest, Ctrl-D leaves. It needs a terminal, and there is no `--yes`: nothing runs without your confirmation.

## Languages: stack profiles

Everything language-specific is data: a **stack profile** says how to recognise a stack, how to scaffold it, which commands
analyse and test it, where code and tests live, and what an LLM should know about its idioms. Packaged: `python`, `node`,
`java` (JDK only: no Maven, Gradle or JUnit) and `flutter`. `ask` picks the stack from your request, and when it matches
none of them it **says so** instead of building the wrong thing:

```
$ minifactory ask "a cobol program that prints hello"
error: no supported stack matches this request (got 'unsupported'; available: flutter, java, node, python). Add one as stacks/<name>.yaml
```

Add a language by dropping a YAML file in your workspace's `stacks/` folder (field reference in [`docs/stacks.md`](docs/stacks.md)):
no code needed.

## Skills: reusable guidance for agent steps
A skill is a `SKILL.md` (YAML frontmatter with `name` and `description`, then markdown) that tells an agent how you want
something done. Add skills from a path or a GitHub URL; a folder or repository with many skills adds them all:
```bash
minifactory skills add ./my-skills
minifactory skills add https://github.com/owner/repo                        # every SKILL.md in the repo
minifactory skills add https://github.com/owner/repo/tree/main/skills       # ...or under one folder
minifactory skills list
```
`add` shows each skill (name, description, size) and asks before copying it to `.minifactory/skills/` in your workspace (`skills_dir` in `minifactory.yaml` changes it; `--global` for
all workspaces). Then a step opts in: `agent.edit`, `agent.plan_app`, `agent.implement_spec` and `agent.repair_build` take
`skills: [tdd, review]`. Only the text is used: scripts next to a `SKILL.md` are not copied and nothing is executed.
A skill goes into a prompt, so read third-party ones first.

## Fix a bug in an existing repo

```bash
minifactory workflows copy fix-bug
minifactory ask "the counter goes up by 2 instead of 1 in acme/todo_app" --dry-run
```

`fix-bug` clones the repo with `gh`, requires the repo to analyse cleanly, selects the relevant files, writes a test
that reproduces the bug (and stops without changing anything if that test does not fail), fixes it with an
exact-match patch, re-runs the checks, enforces a size limit on the change, and opens a pull request.
It never touches the default branch.

## Let the factory write workflows

```bash
minifactory workflows copy create-workflow
minifactory ask "create a workflow that clones a GitHub repo, runs dart format and opens a pull request"
minifactory workflows list                    # the result is listed under "drafts"
minifactory workflows enable dart-format-pr   # shows what it would do, asks, then activates it
```

The agent reads a catalog generated from the plugins installed *right now* (`minifactory plugins --schema` prints the same
text), writes `draft.yaml`, and must pass the same validator as any workflow; errors go back to it through the usual repair
loop. If the goal needs something that does not exist it declines with `MISSING: <what>` instead of inventing a step.
The result is only ever a **draft**: it is not routable by `ask` and never runs until you enable it, and `enable` first lists
every shell command, repository write and paid LLM call it contains.

## Design principles

- **Commands see no credentials by default.** The generated code and the tests of a repository you clone run with a filtered
  environment (no AWS keys, tokens or API keys; `pass_env` adds names on purpose). Files are not hidden: a sandboxed runner is next.

- **Untrusted agent output.** Edits are parsed strictly: a `PATCH` must match exactly once or nothing is written;
  paths cannot escape the repo; plans are validated with pydantic; the Bedrock provider rejects a reply cut off by the token limit.
- **Bounded loops.** Repair attempts, unproductive attempts, features per plan and context size all have budgets.
- **Deterministic gates after every agent step.** `on_fail: discard` stops a job without changing anything;
  `blocking: false` lets enrichment steps annotate a result without stopping it.
- **Generated workflows are drafts.** A person reviews and enables them; nothing an LLM wrote runs on its own.
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
from minifactory.core.context import Step, StrictParams
from minifactory.core.models import StepResult
from minifactory.core.registry import register

class Params(StrictParams):          # unknown keys in the YAML are errors
    message: str

@register("step", "demo.hello")
class Hello(Step):
    Params = Params
    def run(self, ctx, p):
        return StepResult.ok(f"hello {ctx.job.name}: {p.message}")
```

```bash
minifactory run my-workflow --plugin my_plugin
```

Installed packages can instead expose the `minifactory.plugins` entry point and are discovered automatically.
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
- Stack profiles ship for Python, Node, Java (JDK only) and Flutter. A Maven/Gradle project needs your own profile.
- The gates check that generated code is *consistent* (it builds and its own tests pass), not that it does what you meant:
  a generated Java "first twenty primes" program printed the primes up to a limit, and passed its own tests.
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
