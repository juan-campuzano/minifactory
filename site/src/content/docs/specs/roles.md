---
title: Role Profiles & Per-Role LLMs
description: Complete schema for defining agent roles (personas, default skills, file boundaries) and assigning dedicated LLMs per role.
---

In `minifactory`, an agent **role** is declarative YAML data (`RoleProfile`) that defines four things:
1. **Perspective (`persona`)**: Injected into the agent step's prompt (`ROLE: <name> (<description>)\n<persona>`).
2. **Default guidance (`skills`)**: Installed `SKILL.md` files automatically included whenever the role runs.
3. **File-path boundaries (`allowed_prefixes`, `forbid_prefixes`, `tests_only`)**: Deterministic path checks enforced before any file or patch is written to disk.
4. **Dedicated LLM (`llms.<role>`)**: Optional per-role LLM provider override in the workflow YAML, keeping the role profile itself provider-agnostic.

## `RoleProfile` Schema

Packaged roles live in `minifactory/profiles/roles/*.yaml`. You can create new roles or override packaged ones by placing `<workspace>/roles/<name>.yaml` in your workspace.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | `str` (`^[a-z][a-z0-9_-]{0,30}$`) | **Yes** | — | Role identifier referenced in `role: <name>` on `agent.*` steps and `llms.<name>` in workflows. |
| `description` | `str` | **Yes** | — | One-line summary shown in prompts and in `minifactory plugins --schema`. |
| `persona` | `str` | **Yes** | — | Role instructions, priorities, and constraints injected into the prompt. |
| `skills` | `list[str]` | No | `[]` | Default installed skills (`minifactory skills add`) merged with the step's own `skills:`. |
| `allowed_prefixes` | `list[str]` | No | `[]` | If non-empty, the role may **only** create or edit files starting with one of these prefixes. |
| `forbid_prefixes` | `list[str]` | No | `[]` | File path prefixes this role is **forbidden** from editing. Any violation rejects the edit before writing. |
| `tests_only` | `bool` | No | `false` | When `true`, automatically restricts edits to the active stack's `test_prefixes` (`tests/`, `test/`, `src/test/`). |

## Packaged Roles

| Role | Purpose | Enforced File Boundaries |
|---|---|---|
| `designer` | UI/UX, design system tokens, component hierarchy, and visual state feedback | `forbid_prefixes: [test/, tests/, src/test/]` |
| `developer` | Clean feature/bug implementation following architecture and design specs, paired with tests | Unrestricted (bounded by step `allowed_prefixes` if given) |
| `architect` | Decomposing requirements into small vertical slices, module boundaries, and contracts | Used primarily in `agent.plan_app` / `agent.locate_files` |
| `qa` | Reproduction tests, boundary conditions, and regression suites | `tests_only: true` (confined to the stack's test directories) |
| `reviewer` | Critical code/PR review focused on bugs, security, and missing tests | Read-only (`agent.review_pr`) |

## Creating a Custom Role in Your Workspace

Create `roles/frontend-designer.yaml` inside your workspace:

```yaml
name: frontend-designer
description: Brand UI/UX & accessible component specialist
persona: |
  You are the Lead Product Designer.
  - Define colour, spacing, and typography tokens in DESIGN.md before building widgets.
  - Ensure WCAG AA contrast and explicit empty, loading, and error states.
  - Do not implement backend/network logic or test suites.
skills:
  - brand-guidelines
allowed_prefixes:
  - DESIGN.md
  - lib/theme/
  - lib/widgets/
forbid_prefixes:
  - test/
  - lib/data/
```

## Assigning Different LLMs per Role (`llms:`)

A workflow can define a default `providers.llm` and override specific roles under `llms:`. Every call made through a role-specific LLM is recorded in `events.jsonl` with `role: "<name>"`:

```yaml
providers:
  llm:
    use: bedrock
    with:
      model_id: "us.anthropic.claude-haiku-4-5-20251001-v1:0"
      region: us-east-1

llms:
  designer:
    use: bedrock
    with:
      model_id: "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
      region: us-east-1

steps:
  - id: design
    use: agent.edit
    with:
      role: designer
      instruction: "Create DESIGN.md and theme tokens for ${job.description}"

  - id: implement
    use: agent.implement_spec
    with:
      role: developer
      features: "${steps.plan.outputs.features}"
```
