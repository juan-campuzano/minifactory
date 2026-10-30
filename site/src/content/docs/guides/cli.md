---
title: CLI Reference
description: Complete command-line reference for minifactory ask, chat, run, validate, workflows, skills, doctor, plugins, and completion.
---

## `minifactory ask` — Natural Language to Workflow

Routes a free-text request to a workflow with a `route:` block, drafts the `Job` via the workflow's `intake` plugin, and asks for confirmation before running:

```bash
minifactory ask "a simple python cli that counts lines in a file"
minifactory ask "fix the off-by-one error in acme/calc" --dry-run
minifactory ask "review PR 285 in bancolombia/dart-code-linter" --router keyword
```

Key flags:
- `--router jev|keyword`: Router plugin (`jev` uses TypeSafe Jev and requires `TYPESAFE_API_KEY`; `keyword` runs offline).
- `--threshold FLOAT`: Minimum confidence (`0.0`–`1.0`, default `0.7`).
- `--dry-run`: Route and draft the `Job` input without executing the workflow.
- `--yes`: Non-interactive confirmation (only proceeds if a workflow is chosen, `confidence >= threshold`, and `actionable == True`).
- `--output local|github`: Where new projects are delivered (`--output-dir DIR` for local; `--owner ORG` and `--public` for GitHub).

## `minifactory chat` — Interactive Session with Memory

```bash
minifactory chat [--router keyword]
```

Runs the `ask` flow in an interactive loop with conversational memory:
- If a follow-up omits the repository or pull request number (e.g., *"review the PR again"* or *"now fix that bug"*), `chat` completes it using the last repository/PR from the session and shows the drafted input for confirmation.
- Built-in slash commands: `/workflows`, `/history`, `/last`, `/forget`, `/help`, `/exit`.

## `minifactory run` & `minifactory validate`

```bash
minifactory validate <workflow-name-or-path>
minifactory run <workflow-name-or-path> [--resume] [--only JOB_ID] [--limit N] [--plain] [--quiet]
```

- `validate` checks the YAML schema, step names, `StrictParams`, required providers (`scm`, `llm`, `llms`), `when` expressions, and step output references without running anything.
- `run --resume` skips steps that already finished `ok` in `.minifactory/runs/<workflow>/<job>/state.json`.

## `minifactory workflows`

```bash
minifactory workflows list             # workspace workflows, drafts, and packaged templates
minifactory workflows copy <template>  # copy a packaged template into workflows/
minifactory workflows enable <draft>   # review findings and move workflows/drafts/<name>.yaml to workflows/
```

## `minifactory skills`

```bash
minifactory skills add <path-or-github-url> [--global] [--yes]
minifactory skills list
```

## `minifactory plugins` & `minifactory doctor`

```bash
minifactory plugins                    # list registered plugins by kind
minifactory plugins --schema [--json]  # print full step/provider/stack/role catalog
minifactory doctor [WORKFLOW] [--online] [--json]
```
