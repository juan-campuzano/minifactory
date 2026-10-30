---
title: Skills (SKILL.md)
description: Reusable markdown instructions for agent steps, installed from local paths or GitHub repositories.
---

A **skill** is a `SKILL.md` file with YAML frontmatter (`name` and `description`) and a Markdown body containing instructions or conventions for agent steps.

## Format Specification

```markdown
---
name: tdd
description: Write focused deterministic unit tests covering edge cases
---
Always test boundary conditions (empty input, single element, invalid types).
Keep tests fast and independent of network or wall-clock time.
```

Validation rules enforced by `minifactory.skills`:
- `name` must match `^[a-z][a-z0-9_-]{1,60}$` (defaults to the parent folder name if omitted).
- `description` is required in the YAML frontmatter.
- The Markdown body must be non-empty.
- Each `SKILL.md` is capped at **20,000 characters** (`MAX_SKILL_CHARS`), and the combined skills passed to a single step are capped at **24,000 characters** (`MAX_PROMPT_CHARS`). Oversized or missing skills fail the step before any LLM call is made.

## Installing & Listing Skills

```bash
minifactory skills add ./my-skills
minifactory skills add https://github.com/owner/repo
minifactory skills add https://github.com/owner/repo/tree/main/skills
minifactory skills add https://github.com/owner/repo --global
minifactory skills list
```

:::caution[Security model]
`minifactory skills add` copies **only** the `SKILL.md` text file into `<workspace>/.minifactory/skills/<name>/SKILL.md` (or `~/.config/minifactory/skills/` with `--global`) after showing a summary and asking for confirmation. Companion scripts in the source repository are never copied or executed. Because skill text is injected into LLM prompts, always review third-party skills before adding them.
:::

## Using Skills in Steps and Roles

Pass `skills: [<name>, ...]` to `agent.plan_app`, `agent.implement_spec`, `agent.edit`, `agent.repair_build`, or `agent.review_pr`, or attach default `skills:` to a [Role Profile](/minifactory/specs/roles/):

```yaml
- id: implement
  use: agent.implement_spec
  with:
    role: developer
    skills: [tdd]
    features: "${steps.plan.outputs.features}"
```
