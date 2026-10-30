---
title: Workflow YAML Format
description: Complete specification of a minifactory workflow YAML file, templating, conditions, failure modes, and providers.
---

A workflow is a single declarative YAML file (`schema_version: 1`). Unknown keys at any level are rejected at load time.

## Full Workflow Structure

```yaml
schema_version: 1
name: my-workflow                 # required, unique identifier

route:                            # optional: makes `minifactory ask` able to choose this workflow
  description: One sentence explaining when to use this workflow
  not_for:
    - requests this workflow must NOT handle
  examples:
    - "a sample user request"
  needs: what a request must contain to be actionable
  intake: app-spec                # registered `intake` plugin (app-spec, repo-task, repo-feature, pr-ref, workflow-goal)
  delivery: choose                # `choose` (--output local|github) or `fixed` (delivers to its own target)

vars:                             # optional constants referenced as ${vars.<key>}
  max_lines: 300

source:                           # required: where jobs come from
  use: app-specs
  with: { path: projects }

executor:                         # optional (default: local; or `threads`)
  use: local

runner:                           # optional: how shell commands run (default: `host` with filtered env)
  use: host

providers:                        # infrastructure ports required by steps
  scm:
    use: local-dir
    with: { dir: output }
  llm:
    use: bedrock
    with:
      model_id: "us.anthropic.claude-haiku-4-5-20251001-v1:0"
      region: us-east-1

llms:                             # optional: per-role LLM overrides (falls back to providers.llm)
  designer:
    use: bedrock
    with:
      model_id: "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
      region: us-east-1

steps:
  - id: scaffold
    use: stack.scaffold

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

  - id: test
    use: stack.check
    with: { check: test }
    on_fail: continue

  - id: repair
    use: agent.repair_build
    when: "steps.test.status == 'failed'"
    with:
      role: developer
      checks: [analyze, test]
```

## Templating (`${...}`) & Expressions (`when:`)

- **Interpolation (`${...}`)**: Available in `with:` parameter values:
  - `${job.<attr>}` — job attributes (`id`, `name`, `stack`, `description`, etc.).
  - `${steps.<id>.outputs.<key>}` and `${steps.<id>.status}` — outputs and status of **earlier** steps (forward references are rejected at validation time).
  - `${vars.<key>}` — workflow constants from `vars:`.
  - `${env.python}` — quoted path to the current Python interpreter.
- **Conditions (`when:`)**: A safe subset of Python expressions (`==`, `!=`, `<`, `<=`, `>`, `>=`, `in`, `not in`, `and`, `or`, `not`, attribute access, literals). Function calls, indexing, and loops are forbidden.
- **Failure handling (`on_fail:` & `blocking:`)**:
  - `on_fail: fail` (default) — stops the job with outcome `failed`.
  - `on_fail: discard` — stops the job cleanly with outcome `discarded` (used for baseline or reproduction gates when a job should be skipped without error).
  - `on_fail: continue` — records the step status and continues so a subsequent step (like `agent.repair_build`) can inspect `steps.<id>.status`.
  - `blocking: false` — a failure is appended to `notes` (surfaced in the PR body) and never fails the job.
