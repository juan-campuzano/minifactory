---
title: Workspaces & Config
description: How minifactory discovers workspaces, resolves relative paths, and reads minifactory.yaml.
---

Code ships in the `minifactory` Python package; your workflows, custom stack profiles, custom role profiles, and skills live in a **workspace**.

## Discovery Rules

`minifactory` locates the active workspace like `git`:
1. The nearest folder containing `minifactory.yaml` walking upward from the current working directory.
2. Otherwise, the global workspace at `$XDG_CONFIG_HOME/minifactory` (default `~/.config/minifactory`).
3. If neither exists, commands resolve paths relative to the current directory.

When a workspace is found, the CLI changes its working directory to the workspace root so **every relative path inside a workflow resolves from the workspace root** (while file paths passed on the CLI are resolved relative to where you invoked the command first).

## Workspace Layout

```text
my-factory/
  minifactory.yaml          # optional workspace configuration (schema_version: 1)
  workflows/                # active workflows (routable by `minifactory ask`)
    drafts/                 # workflows drafted by `create-workflow` (inactive until enabled)
  roles/                    # optional custom or overridden role profiles (<name>.yaml)
  stacks/                   # optional custom or overridden stack profiles (<name>.yaml)
  .minifactory/
    skills/<name>/SKILL.md  # installed skills (committable to git)
    runs/                   # generated per-job state, workdirs, and events.jsonl (git-ignored)
  output/                   # default destination for `--output local` (git-ignored)
```

## `minifactory.yaml` Schema

All keys are optional (`extra="forbid"`). Precedence is always: **CLI flag > `minifactory.yaml` > default**.

```yaml
schema_version: 1
workflows_dir: workflows          # active workflows directory
runs_dir: .minifactory/runs       # state, workdirs, and events.jsonl
output_dir: output                # parent directory for `--output local`
skills_dir: .minifactory/skills   # where `minifactory skills add` installs SKILL.md files
router: jev                       # default router plugin (`jev` or `keyword`)
threshold: 0.7                    # minimum router confidence to run with `--yes`
plugins: []                       # extra Python module names to import on startup
```
