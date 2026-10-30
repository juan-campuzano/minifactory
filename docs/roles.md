# Role profiles: personas, boundaries and per-role LLMs

Like stack profiles (`docs/stacks.md`), agent **roles** are YAML data. A role defines an agent's perspective
(`persona`), its default `skills`, which file paths it is allowed or forbidden to edit (`allowed_prefixes`,
`forbid_prefixes`, `tests_only`), and can be paired with a dedicated LLM in the workflow (`llms.<role>`).

Packaged roles (`minifactory/profiles/roles/`): `architect`, `designer`, `developer`, `qa`, `reviewer`.
Add or override roles in `<workspace>/roles/<name>.yaml` (a workspace role with the same name wins).

```yaml
name: designer                      # lowercase: ^[a-z][a-z0-9_-]{0,30}$
description: UI/UX, design system, component structure and visual hierarchy specialist
persona: |                          # injected into the prompt as ROLE: <name> (<description>)
  You are the Product Designer. Focus on visual hierarchy, intuitive user flows,
  reusable design tokens (colours, typography, spacing), accessibility, and explicit
  state feedback (empty, loading, error, populated).
skills: []                          # installed skills (`minifactory skills add`) always included for this role
allowed_prefixes: []                # if non-empty, edits outside these prefixes are rejected
forbid_prefixes:                    # edits matching any of these prefixes are rejected before writing
  - test/
  - tests/
  - src/test/
tests_only: false                   # true: restricts edits to the active stack's `test_prefixes`
```

## Using roles and per-role LLMs in a workflow

Every `agent.*` step (`agent.plan_app`, `agent.implement_spec`, `agent.edit`, `agent.repair_build`,
`agent.locate_files`, `agent.review_pr`, `agent.llm_migrate`) accepts `role: <name>`.

To use a different model for a specific role while keeping the role profile provider-agnostic, add `llms:` to
the workflow. Steps whose role is not in `llms:` fall back to `providers.llm`:

```yaml
providers:
  scm: { use: local-dir, with: { dir: output } }
  llm:
    use: bedrock
    with: { model_id: "us.anthropic.claude-haiku-4-5-20251001-v1:0", region: us-east-1 }

llms:
  designer:
    use: bedrock
    with: { model_id: "us.anthropic.claude-sonnet-4-5-20250929-v1:0", region: us-east-1 }

steps:
  - id: plan
    use: agent.plan_app
    with: { role: architect }

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
