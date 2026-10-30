---
title: Steps & Plugins Catalog
description: Auto-generated reference of all built-in steps, providers, intakes, stacks, and roles.
---

:::note[Auto-generated from code]
This page is generated directly from `minifactory.catalog.describe()`, `minifactory.stacks.available()`,
and `minifactory.roles.available()`. Run `minifactory plugins --schema` in your terminal to see this
including any custom workspace stacks, roles, or third-party plugins.
:::

## Steps (`steps:` -> `use:`)

### `agent.edit` — requires `llm`

One bounded LLM edit: show these files, apply the reply (patches or whole files), commit.

| Parameter | Type | Requirement / Default |
|---|---|---|
| `instruction` | `string` | **required** |
| `stack` | `string` | `None` |
| `role` | `string` | `None` |
| `tests_only` | `boolean` | `False` |
| `files` | `list[string]` | _optional_ |
| `extra_files` | `list[string]` | _optional_ |
| `skills` | `list[string]` | _optional_ |
| `extra` | `string` | `''` |
| `allowed_prefixes` | `list[string]` | _optional_ |
| `commit_message` | `string` | `'chore: automated edit'` |
| `max_context_chars` | `integer` | `60000` |

### `agent.implement_spec` — requires `llm`

One LLM call and one commit per feature. The loop lives here, not in the YAML.

| Parameter | Type | Requirement / Default |
|---|---|---|
| `features` | `list[object]` | **required** |
| `stack` | `string` | `None` |
| `role` | `string` | `None` |
| `context_globs` | `list[string]` | `None` |
| `max_features` | `integer` | `10` |
| `max_context_chars` | `integer` | `60000` |
| `skills` | `list[string]` | _optional_ |

### `agent.llm_migrate` — requires `llm`

One LLM call that rewrites the listed files following an instruction (a migration), then commits.

| Parameter | Type | Requirement / Default |
|---|---|---|
| `instruction` | `string` | **required** |
| `files` | `list[string]` | **required** |
| `role` | `string` | `None` |
| `commit_message` | `string` | `'chore: automated migration'` |

### `agent.locate_files` — requires `llm`

Select, don't generate: the LLM picks files from the real list of tracked files, and anything it names that is not in that list is discarded.

| Parameter | Type | Requirement / Default |
|---|---|---|
| `task` | `string` | **required** |
| `stack` | `string` | `None` |
| `role` | `string` | `None` |
| `globs` | `list[string]` | `None` |
| `max_files` | `integer` | `8` |
| `max_tree` | `integer` | `400` |

### `agent.plan_app` — requires `llm`

Spec -> validated list of features, sized to what the user asked for. The LLM output is untrusted: it is parsed and validated with pydantic, and anything malformed fails the job here, not three steps later. A plan over the size budget gets one chance to be redone smaller.

| Parameter | Type | Requirement / Default |
|---|---|---|
| `stack` | `string` | `None` |
| `role` | `string` | `None` |
| `skills` | `list[string]` | _optional_ |

### `agent.repair_build` — requires `llm`

verify -> ask LLM -> apply -> verify, until green or a budget runs out.

| Parameter | Type | Requirement / Default |
|---|---|---|
| `verify_cmd` | `string` | `''` |
| `stack` | `string` | `None` |
| `role` | `string` | `None` |
| `checks` | `list[string]` | _optional_ |
| `new_project` | `boolean` | `False` |
| `files` | `list[string]` | _optional_ |
| `globs` | `list[string]` | _optional_ |
| `max_context_chars` | `integer` | `60000` |
| `context` | `string` | `''` |
| `skills` | `list[string]` | _optional_ |
| `max_attempts` | `integer` | `5` |
| `max_unproductive` | `integer` | `2` |
| `commit_message` | `string` | `'fix: repair build after migration'` |
| `timeout` | `integer` | `120` |

### `agent.review_pr` — requires `llm`

One LLM call that reviews the fetched diff. Findings are validated, sorted by severity, limited in number and dropped when they point at a file that is not in the PR. Writes `review.md` next to the run.

| Parameter | Type | Requirement / Default |
|---|---|---|
| `pr` | `string` | `'pr'` |
| `role` | `string` | `None` |
| `focus` | `string` | `''` |
| `max_findings` | `integer` | `12` |
| `skills` | `list[string]` | _optional_ |

### `file.set_key`

A deterministic transform (stand-in for your Gradle scaffold upgrade).

| Parameter | Type | Requirement / Default |
|---|---|---|
| `file` | `string` | **required** |
| `key` | `string` | **required** |
| `value` | `string` | **required** |

### `flutter.analyze`

`flutter analyze` in the repo; the step fails if it reports any issue.

| Parameter | Type | Requirement / Default |
|---|---|---|
| `timeout` | `integer` | `300` |
| `tool` | `auto|real|fake` | `None` |

### `flutter.create`

`flutter create` inside the already-initialised repo. Project name = job name.

| Parameter | Type | Requirement / Default |
|---|---|---|
| `org` | `string` | `'com.example'` |
| `timeout` | `integer` | `300` |
| `tool` | `auto|real|fake` | `None` |

### `flutter.test`

`flutter test`, optionally with coverage and a minimum line-coverage threshold (read from coverage/lcov.info, which real Flutter and the fake both write).

| Parameter | Type | Requirement / Default |
|---|---|---|
| `coverage` | `boolean` | `False` |
| `min_coverage` | `number` | `None` |
| `timeout` | `integer` | `600` |
| `tool` | `auto|real|fake` | `None` |
| `paths` | `list[string]` | `[]` |
| `expect_failure` | `boolean` | `False` |

### `scm.clone` — requires `scm`

Clone the job's repository (its default branch unless `branch` is set) into the work directory.

| Parameter | Type | Requirement / Default |
|---|---|---|
| `branch` | `string` | `None` |

### `scm.diff_limit` — requires `scm`

Blast-radius gate: a fix that rewrites half the repo is not a fix. Compares with the base branch.

| Parameter | Type | Requirement / Default |
|---|---|---|
| `max_files` | `integer` | `8` |
| `max_lines` | `integer` | `300` |

### `scm.guard_no_open_pr` — requires `scm`

Dedupe: don't redo work that already has a branch or an open PR.

| Parameter | Type | Requirement / Default |
|---|---|---|
| `branch` | `string` | **required** |

### `scm.init_repo` — requires `scm`

Create the repository for a brand-new project (instead of cloning an existing one).

_No parameters._

### `scm.open_pr` — requires `scm`

Deliver. Notes collected by earlier steps (e.g. a failed non-blocking coverage phase) are appended to the PR description.

| Parameter | Type | Requirement / Default |
|---|---|---|
| `branch` | `string` | **required** |
| `title` | `string` | **required** |
| `body` | `string` | `''` |

### `scm.pr_comment` — requires `scm`

Post a comment on the pull request, as the person running the factory. Visible to everyone who can see the PR.

| Parameter | Type | Requirement / Default |
|---|---|---|
| `body` | `string` | **required** |

### `scm.pr_fetch` — requires `scm`

Read the pull request in `job.pr` of the job's repository: details, changed files and diff.

| Parameter | Type | Requirement / Default |
|---|---|---|
| `max_diff_chars` | `integer` | `60000` |
| `skip_if_reviewed` | `boolean` | `False` |

### `shell.run`

Run a shell command in the cloned repo; a non-zero exit fails the step (or passes it, with expect_failure).

| Parameter | Type | Requirement / Default |
|---|---|---|
| `cmd` | `string` | **required** |
| `timeout` | `integer` | `120` |
| `expect_failure` | `boolean` | `False` |

### `stack.check`

Run one of the stack's commands (setup, analyze, test or format) in the repository. A stack that has no such command skips the step.

| Parameter | Type | Requirement / Default |
|---|---|---|
| `check` | `setup|analyze|test|format` | **required** |
| `stack` | `string` | `None` |
| `paths` | `list[string]` | `[]` |
| `repro` | `boolean` | `False` |
| `expect_failure` | `boolean` | `False` |
| `timeout` | `integer` | `600` |

### `stack.detect`

Recognise the stack of a cloned repository from its files. Unknown or ambiguous = fails, so a workflow can stop (on_fail: discard) instead of guessing.

| Parameter | Type | Requirement / Default |
|---|---|---|
| `stack` | `string` | `None` |

### `stack.scaffold`

Seed a new project: write the profile's starter files (never over existing ones), run its scaffold commands, commit.

| Parameter | Type | Requirement / Default |
|---|---|---|
| `stack` | `string` | `None` |
| `timeout` | `integer` | `300` |

### `workdir.init`

Create an empty git repository as the work directory, for workflows that clone nothing.

_No parameters._

### `workflow.catalog`

Write CATALOG.md (the format rules and every step, plugin and stack installed, with parameters) and EXAMPLE_<name>.yaml (working workflows) into the work directory, for an agent to read.

| Parameter | Type | Requirement / Default |
|---|---|---|
| `examples` | `list[string]` | `['app-factory', 'fix-bug']` |

### `workflow.save_draft`

Validate the drafted workflow once more and save it under workflows/drafts/. A draft is not routable by `ask` and never runs by itself; `minifactory workflows enable NAME` activates it.

| Parameter | Type | Requirement / Default |
|---|---|---|
| `file` | `string` | `'draft.yaml'` |
| `dir` | `string` | `'workflows/drafts'` |

## Packaged Roles (`role:` on `agent.*` steps)

| Role | Description | Boundaries |
|---|---|---|
| `architect` | Software architect focused on vertical slices, clear module boundaries and contracts | none |
| `designer` | UI/UX, design system, component structure and visual hierarchy specialist | forbid: `test/, tests/, src/test/` |
| `developer` | Software engineer focused on clean implementation, modular code and passing tests | none |
| `qa` | Quality assurance engineer focused on reproduction tests, edge cases and regression suites | `tests_only: true` |
| `reviewer` | Senior code reviewer focused on correctness, security, regressions and test coverage | none |

## Packaged Stacks (`stack:` / `${job.stack}`)

| Stack | Description | Required Tools | Auto-detect Files |
|---|---|---|---|
| `dart` | Dart packages and command-line programs (dart analyze, dart test with package:test). Not Flutter apps: pin it with `stack: dart`. | none | _pinned only_ |
| `flutter` | Flutter/Dart mobile apps (needs the Flutter SDK). Sources in lib/, widget tests in test/. | none | `pubspec.yaml` |
| `java` | Java 17+ with the JDK only (javac and java; no Maven/Gradle, no JUnit). Tests are classes with a main method. | `javac`, `java` | _pinned only_ |
| `node` | Node.js 20+ (CommonJS, no dependencies: node:test and node:assert). Sources at the root or in src/, tests in test/. | `node` | `package.json` |
| `python` | Python 3.11+ (standard library only: unittest, argparse). A package under src/, tests under tests/. | `python3` | `pyproject.toml`, `setup.py`, `setup.cfg`, `requirements.txt` |

## Providers, Sources & Executors

### `scm` plugins

#### `scm: github`

New projects become new GitHub repos (`init_repo`, private by default, with an initial README commit on the default branch); the generated code arrives as a PR from a branch.

**`with:` parameters:** `owner` (`None`), `private` (`True`)

#### `scm: local-dir`

The result is a plain git repo in `<dir>/<name>` (work lands on `main`, no branch, no PR), ready to open in an IDE. Created from scratch: it cannot clone existing repositories.

**`with:` parameters:** `dir` (`'output'`)

#### `scm: local-git`

`remotes_dir/<repo>.git` are the 'remotes'; PRs are JSON files in `prs_dir/<repo>/`.

**`with:` parameters:** `remotes_dir` (**required**), `prs_dir` (**required**)

### `llm` plugins

#### `llm: bedrock`

Credentials come from the normal AWS chain (env, `profile`, SSO...). With `role_arn` the provider first assumes that role (e.g. a cross-account "IA" role).

**`with:` parameters:** `model_id` (**required**), `region` (`None`), `profile` (`None`), `role_arn` (`None`), `max_tokens` (`4096`), `temperature` (`0.0`), `price_per_mtok` (`None`)

#### `llm: fixture`

Replays canned replies from `<path>/<app>/`, so a whole app can be 'generated' offline.

**`with:` parameters:** `path` (**required**)

#### `llm: openai`

POST {base_url}/chat/completions. The API key comes from the secrets port, which is where your cross-account STS assume-role logic would live (as a `secrets` plugin).

**`with:` parameters:** `base_url` (**required**), `model` (**required**), `api_key_secret` (`'LLM_API_KEY'`), `timeout` (`120`)

#### `llm: scripted`

Rule-based stand-in. Understands `replies` (in order) or two tasks on a `build.cfg` file: migrate (sets java_version) and repair (drops an option the build rejects).

**`with:` parameters:** `replies` (`None`)

### `secrets` plugins

#### `secrets: env`

Secrets read from environment variables.

### `source` plugins

#### `source: app-specs`

One job per `*.yaml` spec in a directory: the 'what apps should we build?' queue. A spec needs `name` (also the repo name) and `description`; `features` is optional.

**`with:` parameters:** `path` (**required**)

#### `source: catalog`

Reads a JSON catalog and keeps entries whose `field` is below a threshold, the local equivalent of 'microservices below the target Java version'.

**`with:` parameters:** `path` (**required**), `below` (**required**), `field` (`'java_version'`)

#### `source: repo-tasks`

One job per `*.yaml` in a folder, each with `repo: owner/name` and `task: ...`.

**`with:` parameters:** `path` (**required**)

#### `source: static`

A fixed list of jobs written in the workflow itself (`jobs: [{name: ...}]`).

**`with:` parameters:** `jobs` (**required**)

### `executor` plugins

#### `executor: local`

Run jobs one after another.

#### `executor: threads`

Run up to `workers` jobs in parallel threads.

**`with:` parameters:** `workers` (`4`)

## Intakes (`route.intake`)

- **`app-spec`**: Draft a new-project spec (name, description, features, size, stack) from free text, using the workflow's LLM.
- **`pr-ref`**: Find the pull request in a request: a github.com/owner/name/pull/N URL, or `owner/name` plus `#N` / `PR N`. No LLM: the repository and the number must be written in the text.
- **`repo-feature`**: Extract an `owner/name` repository and the feature wanted from free text (the branch is `factory/feat-...`).
- **`repo-task`**: Extract an `owner/name` repository and a bug description from free text.
- **`workflow-goal`**: Take the user's text as the goal of a new workflow (no LLM needed: the drafting agent reads it as data).
