# AGENTS.md

Single source of truth for any AI coding agent (Claude Code, Codex, Gemini CLI, Cursor, Copilot...).
Tool-specific files (CLAUDE.md, GEMINI.md...) should not exist; if one is needed, make it a one-line pointer here.

## What this is
`minifactory`: a small engine that runs **declarative workflows** (YAML) made of **plugin steps** over a queue of
**jobs**. Environment-specific things (git host, LLM, secrets, where jobs run, what to work on) sit behind **ports**.
Packaged templates (`src/minifactory/templates/<name>/`): `flutter-app-factory` (offline demo: fixture LLM + fake flutter),
`app-factory` (real: Bedrock + the stack's tools; new projects in any stack; the one `ask` uses for them) and `java-migration-demo` (a miniature batch
migration: toy repos, a baseline gate, a repair loop). They are copied into a workspace; the package itself never runs from its own folders.

## Commands
```bash
pip install -e ".[dev,aws]"                       # aws = boto3, only for the bedrock LLM
pytest                                              # no network, no Flutter SDK needed
ruff check src tests examples
mypy                                                # strict; see "Known gaps"
minifactory plugins                                     # list registered plugins
minifactory init my-factory && cd my-factory           # create a workspace
minifactory workflows list | copy NAME                  # packaged templates -> your workspace
minifactory validate flutter-app-factory                # by name (or path); fail-fast checks, runs nothing
minifactory run flutter-app-factory                     # needs a clean demo-flutter/ (rm -rf demo-flutter to reset)
minifactory demo-init && minifactory run java-migration-demo
minifactory run app-factory                         # real LLM (Bedrock); costs tokens
minifactory run ... --plain                             # no colours/live board (automatic when not a TTY)
FACTORY_FLUTTER=fake minifactory run ...                # simulated flutter (tests/demo ONLY); default is the real SDK, error if missing
```

## Free text -> workflow (`minifactory ask`)
`minifactory ask "a simple app to track my expenses" [--dry-run] [--yes] [--threshold 0.7] [--router jev|keyword]`
1. `discover` loads the workspace's `workflows/*.yaml` (then `~/.config/minifactory/workflows`; packaged templates are NOT routable until copied) that have a `route:` block (description, not_for, examples, needs, intake). No block = not routable.
2. A `router` plugin (`jev` = TypeSafe Jev via HTTP, needs `TYPESAFE_API_KEY`; `keyword` = offline) returns a `Decision`
   (choice or None, confidence, probabilities, actionable). For Jev, `actionable` comes from one Noul per workflow built from its
   `route.needs` (what a request must contain to start); only the chosen workflow's answer is used.
3. Policy is in code (`src/minifactory/router.py: check`): `--yes` only acts when choice != none, confidence >= threshold and actionable;
   interactively a vague-but-clear request continues to the drafted input (with a warning), and a low-confidence one lets you pick from the ranking. Nothing runs without confirmation unless `--yes`.
4. The workflow's `intake` plugin (`app-spec`) drafts the Job with the workflow's own `llm` provider; the user text is wrapped as
   data and the result is validated (name must be `^[a-z][a-z0-9_]{1,40}$`). Fixture-LLM workflows cannot draft new specs, so only
   `app-factory`, `fix-bug` and `create-workflow` carry a `route:`.
To make a workflow routable: add `route:` and, if its input isn't an app spec, register a new `intake` plugin.

## Where the result goes (`minifactory ask --output`)
- `--output local [--output-dir DIR]` (default dir `output`): provider `local-dir` -> plain git repo `DIR/<name>` on `main`, git-ignored build
  output removed, factory notes appended to its README. Refuses to overwrite an existing folder.
- `--output github [--owner X] [--public]`: provider `github` (uses `gh`, so `gh auth login` is the only credential) creates a PRIVATE repo
  (README initial commit), pushes branch `factory/<name>` and opens a PR. Public needs `--public`.
- No flag + a terminal: asked interactively. No flag + no terminal or `--yes`: refuses (never guesses a destination).
- Both are `scm` providers; `with_output` in `router.py` swaps the workflow's `scm` block. `OpenPR` labels the artifact via
  `scm.delivery_kind` ("pull_request" / "folder"). `scm.target(name)` is shown before running.

## Layout
- `src/minifactory/core/`: engine, workflow validation, registry, events, expression language, ports. **Never imports a plugin.**
- `src/minifactory/plugins/builtin/`: `providers_*.py` (scm/llm/secrets/source/executor), `steps_*.py` (steps),
  `flutter_tool.py` + `fake_flutter.py` (flutter CLI shim and its deterministic fake), `util.py` (git, shell, edit protocol).
- `src/minifactory/router.py`: discovery + confidence policy for `ask`. Plugins: `routers.py` (kind `router`), `intakes.py` (kind `intake`).
- `src/minifactory/ui.py`: the pretty CLI (rich live board + summary). Only an event subscriber; `cli.py` falls back to plain sinks.
- `src/minifactory/workspace.py` (find/init/config), `src/minifactory/templates.py` + `src/minifactory/templates/` (packaged workflows and their `assets/`: specs = jobs, fixtures = canned LLM replies).
- `assets/brand/`: logo kit (svg/png/favicon, palette in its README; `python3 assets/brand/_build/build.py` regenerates it). README images use ABSOLUTE
  raw.githubusercontent URLs because PyPI does not resolve relative paths; use the PNGs there (PyPI strips `<picture>`, so the `<img>` fallback is the light logo).
  Binaries live in git history forever: commit a changed PNG deliberately, not on every tweak.
- `examples/` (plugin example), `docs/plugins.md`, `tests/`.
- Run artifacts: `.minifactory/runs/<workflow>/<job>/{state.json,result.json,work/}` and `events.jsonl`. Generated, git-ignored.

## Changing existing repositories (`fix-bug` template)
`minifactory ask "fix X in owner/repo: ..."` -> router -> `repo-task` intake (needs `owner/name` literally in the text; the LLM only extracts it,
and a repo that does not appear in the request is rejected) -> workflow `route.delivery: fixed` (no `--output`: it always opens a PR on that repo).
Steps: guard -> clone -> baseline (`flutter.analyze`, discard if red) -> `agent.locate_files` (LLM *selects* from `git ls-files`; invented paths are
dropped) -> `agent.edit` writes ONE repro test (`allowed_prefixes: [test/]`) -> `expect_failure` gate (a passing test, a missing SDK, a timeout or a
compile error never count as "reproduced"; not reproduced = discarded, nothing changed) -> `agent.edit` fixes -> analyze/test -> repair -> `scm.diff_limit`
(blast radius: 8 files / 300 lines) -> PR. The default branch is never touched.
Edits use `util.apply_reply`: `PATCH:` blocks (exact SEARCH must match exactly once, all-or-nothing) or `FILE:` blocks (full content).
Verified 2026-10-20 with real Haiku 4.5 + Flutter on a repo with an injected bug (`+= 2` instead of `+= 1`): repro test red, one-line fix, 4 tests green.
Not verified: a real GitHub repo (the run used a local-git remote), big repos, bugs spanning several files, `add-feature` (not built).

## Workflows that write workflows (`create-workflow` template)
`ask "create a workflow that ..."` -> `workflow-goal` intake (no LLM; the text is the goal) -> `workdir.init` -> `workflow.catalog` writes
`CATALOG.md` (generated from the registry by `minifactory/catalog.py`: format rules + every step/plugin with parameters; plugins need their OWN
class docstring, it is the description) and `EXAMPLE.yaml` -> `agent.edit` writes `draft.yaml` (`allowed_prefixes: [draft.yaml]`) -> `minifactory validate`
is the gate -> `agent.repair_build` with `context` (validator errors in, patches out) -> `workflow.save_draft` writes `workflows/drafts/NAME.yaml`
(never overwrites; name must match `^[a-z][a-z0-9_-]{1,60}$`) and adds `review:` notes (`minifactory/review.py`: shell commands, repo writes,
GitHub/LLM spend, missing `route:`). Drafts are NOT discovered by `ask` (`discover` globs only the top folder). `minifactory workflows enable NAME`
re-validates, prints the review, asks (or `--yes`) and moves the file. If the goal needs a nonexistent step the agent must reply `MISSING: ...`
(reported by `agent.edit` as its failure reason). Only existing steps are composed: the agent never writes Python plugins.
Verified 2026-10-20 with Haiku 4.5: a feasible goal gave a valid 4-step draft in 1 call (~$0.006); a Slack goal ended in `MISSING: slack.post`.
Not done: a dry-run of the draft with fake providers (it is validated, reviewed and not executed); judging whether a *valid* draft is *sensible*
is the reviewer's job (e.g. the dart-format draft picked the `repo-task` intake, which expects a bug description).

## Stack profiles (languages)
All language knowledge is data in `src/minifactory/profiles/*.yaml` (python, node, java, flutter) plus the workspace's `stacks/*.yaml`
(`minifactory/stacks.py`; field reference in `docs/stacks.md`). Generic steps read them: `stack.detect` (existing repo), `stack.scaffold`,
`stack.check` (setup/analyze/test/format; `repro` + `expect_failure` = "the bug is reproduced" gate with `broken_test_patterns`), and
`agent.plan_app`/`implement_spec`/`edit`/`locate_files`/`repair_build` take `stack` (default: `${job.stack}`). The `app-spec` intake lists the
INSTALLED stacks to the LLM and refuses `unsupported`/unknown ones; `fix-bug` detects the stack from files (`detect`, ambiguity = fails).
Two kinds of guidance on purpose: `hints` (how tests are written: always shown) and `new_project_hints` (layout/constraints: only for projects we
create; showing them for an existing repo made the LLM invent a package path from the job name `acme/textkit`).
Lessons (2026-10-20): `compileall` wrote .pyc into the repo (stale bytecode + bytecode in the PR): analyze must not write; a stack's test run must fail
when it finds no tests; the Dart bias came from `agent.plan_app`'s hardcoded `lib/todo.dart` example, so no step may embed a language.
Verified with Haiku 4.5 and the real toolchains: python CLI, node script and java program created and passing their own checks; a python bug fixed
with a one-line change + regression test; `cobol` rejected. Not verified: Maven/Gradle (no profile), sandboxing (see gaps).

## Workspace (installable layout)
Code ships in the package; user content lives in a workspace found like git: nearest `minifactory.yaml` upward from the cwd, else the global
`$XDG_CONFIG_HOME/minifactory` (default `~/.config/minifactory`), else none (then everything is relative to the cwd, as in development).
`minifactory.yaml` keys (all optional, `extra=forbid`, `schema_version: 1`): `workflows_dir runs_dir output_dir router threshold plugins`.
Precedence: CLI flag > minifactory.yaml > default. When a workspace is found the CLI `chdir`s to its root, so **relative paths inside a
workflow resolve from the workspace root**; a file path given on the command line is made absolute first. Workflows also carry
`schema_version` (only 1 exists). `minifactory workflows copy` skips identical existing files and refuses to overwrite ones you edited.
`run_shell` adds `src/` to `PYTHONPATH` only for a source checkout.

## Naming
Package, import name and command are all `minifactory` (the bare name `factory` is factory_boy's import name: never reuse it). Workspace file
`minifactory.yaml`, runs folder `.minifactory/`, entry-point group `minifactory.plugins`. Kept on purpose: env var `FACTORY_FLUTTER`, the
`factory/<name>` branch prefix on delivered work, and the `factory` git author of automated commits.

## Hard rules
1. The core never imports a plugin. Plugins register with `@register(kind, name)`; kinds: `step source executor scm llm secrets`.
2. Step params are a `StrictParams` subclass (unknown keys are errors). Steps return `StepResult`; never raise for expected failures.
3. The workflow language stays tiny: sequence, `when`, `on_fail`, `blocking`, `${...}`. No loops, calls or arithmetic in YAML:
   if you need them, write a Python step (see `agent.implement_spec`).
4. LLM output is untrusted. Validate with pydantic (`agent.plan_app`), confine paths with `safe_path`, bound loops with budgets
   (`max_attempts`, `max_unproductive`, `max_features`, `max_context_chars`). Follow every agent step with a deterministic gate.
5. Enrichment (coverage, work items...) uses `blocking: false`: it may annotate the PR but never stop it.
6. Tests must not need the network, credentials or the Flutter SDK: use the `fixture`/`scripted` LLMs and `fake_flutter`.

## Python standards (new and changed code)
- Full type hints; `mypy --strict`-clean; pydantic models for any data crossing a step boundary.
- No bare `except`, no `print` outside `cli.py` (use `ctx.emit` events), `pathlib` over `os.path`.
- Shell only through `util.run_shell` (it sets `PYTHONPATH` so `python -m minifactory...` works from step commands).
- Small, surgical diffs: don't reformat or "improve" code you weren't asked to touch; mention unrelated issues instead.
- Every new plugin ships with a test; every bug fix ships with a test that failed before.

## Adding a plugin
See `docs/plugins.md` and `examples/hello_plugin.py`. Load it with `--plugin module` or the `minifactory.plugins` entry point.

## Known gaps / not done
- NO SANDBOX: `run_shell` runs generated code and test commands on the host. The packaged profiles avoid dependency installs on purpose
  (stdlib-only), but a user profile or an LLM-edited manifest can add them. A container executor is the missing piece.
- Gates prove consistency, not intent (a generated Java "first 20 primes" printed primes up to a limit and passed its own tests).
- Open-source readiness: MIT LICENSE (holder "Juan Campuzano", inferred from the account name: confirm). CI (`.github/workflows/ci.yml`)
  passes on Python 3.11 and 3.13 (first run 2026-10-20). `minifactory` was free on PyPI on 2026-10-20 (HTTP 404) but is NOT reserved:
  publishing needs a PyPI account and token (or Trusted Publishing), which the factory does not have.
- `jev` router has only been tested with an injected transport (request shape follows docs.typesafe.ai/api, 2026-10-20); no live
  call yet. The 0.7 threshold is a starting value to calibrate on real requests. Jev cost/latency not measured.
- `github` provider verified only against a fake `gh` (tests); it has NOT been run against real GitHub. Creating the first real repo
  should be done on purpose by the user. Pushes use `gh auth git-credential`, not the machine's configured git credential helper.
- Real runs (2026-10-20, Haiku 4.5, Flutter real): a 1-line counter app succeeded and was delivered; an "expense tracker" (8 features)
  failed: features implemented independently do not agree (undefined `ExpenseItem`), repair exhausted 4 attempts, ~$0.48. Bigger apps
  need better context/ordering between features (not solved).
- Brownfield: only Flutter/Dart (analyze/test steps are Flutter's; other stacks need their own steps or `shell.run`). The repro test lives in
  `test/factory_repro_test.dart` and stays in the PR as a regression test.
- Intakes: `workflow-goal` (goal of a new workflow), `app-spec` (new apps) and `repo-task` (bug in an existing repo). Adding workflows for existing repos (fix a bug, write tests...) needs new intakes.
- LLM usage: providers may implement `complete_ex(system, prompt) -> (text, usage)`; only `bedrock` does (tokens + optional
  `cost_usd` from `price_per_mtok`, whose values are set by the user and must be re-checked). `openai` reports no tokens yet.
- Real-LLM runs of the Flutter workflow (Bedrock, `FACTORY_FLUTTER=real`, `todo_app`), measured on 2026-10-20:
  Claude Haiku 4.5 SUCCEEDED (analyze ok, 1 test failure fixed by 1 repair attempt, coverage >= 80%, 4 LLM calls,
  ~14k in / 6.8k out tokens, ~$0.05 using the assumed price of $1/$5 per 1M tokens: verify). Nova Lite (plan/format errors)
  and Llama 3.3 70B (5 features, 48-177 analyze issues, repair budget exhausted) did NOT produce a green app.
  Only one app and one run per model: not a benchmark. `claude-haiku-5-5` is not enabled for the test account.
- No plugins yet for other git hosts (only GitHub via `gh`), cross-account/STS secrets, graph or database job sources, or a remote executor
  (e.g. AWS Batch): each is one plugin implementing an existing port (see `docs/plugins.md`).
- `scm.init_repo` is an optional capability of the provider (not in the `SCMProvider` Protocol); only `local-git` has it.
- Re-running the Flutter workflow when a job *failed* after `init` fails at `init` (repo exists): reset `demo-flutter/`.
- Real `FACTORY_FLUTTER=real` runs were not exercised in tests; the Dart fixtures are plausible but unverified against the SDK.

## Flutter tool selection
`flutter.*` steps and `flutter_tool` pick the binary by: step param `tool` > `$FACTORY_FLUTTER` > `auto` (= real SDK on PATH; a missing SDK
is an error, never a silent fake). `fake` is a simulator for tests/offline demos: its projects are NOT real (no flutter dependency in
pubspec, no platform folders) and its analyze/test prove nothing. the `flutter-app-factory` template (fixture demo) pins `tool: fake`;
`app-factory` uses the stack's real tools. Lesson learned 2026-10-20: a default of fake shipped a fake project to GitHub.

## App size (`size` in the spec)
`minimal | standard | full` (default standard). The `app-spec` intake infers it from the request ("minimal", "simple" -> minimal).
`agent.plan_app` turns it into a feature budget in code (`SIZE_BUDGET`: 2 / 5 / 8) and tells the LLM; an oversized plan gets ONE retry with
the limit spelled out, then fails rather than overbuild. Measured 2026-10-20 (Haiku 4.5, real Flutter, same request "a minimal app with a
counter..."): before 5 features / 25 tests / 1 repair; after 1 feature / 3 tests / no repair, 2 LLM calls, ~$0.009.
