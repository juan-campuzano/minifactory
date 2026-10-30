---
title: Workflow Templates
description: Overview of the packaged workflow templates included with minifactory.
---

Copy any packaged template into your workspace with:

```bash
minifactory workflows list
minifactory workflows copy <name>
```

Only workflows present in your workspace's `workflows/` directory are routable by `minifactory ask`.

## Packaged Templates

| Template | Routable (`ask`) | Intake | Delivery | Description |
|---|---|---|---|---|
| `app-factory` | Yes | `app-spec` | `choose` (`local` or `github`) | Scaffolds, plans, implements, analyzes, tests, repairs, and delivers a brand-new project in any installed stack (`python`, `node`, `java`, `flutter`, `dart`). |
| `fix-bug` | Yes | `repo-task` | `fixed` (PR on target repo) | Clones an existing repo, checks baseline health, locates relevant files, writes a reproduction test (`expect_failure: true`), applies a minimal fix, verifies `scm.diff_limit`, and opens a PR. |
| `add-feature` | Yes | `repo-feature` | `fixed` (PR on target repo) | Clones an existing repo, detects or pins the stack, locates files, implements the feature + tests in one edit, runs analyze/test + repair, checks `scm.diff_limit`, and opens a PR. |
| `review-pr` | Yes | `pr-ref` | `fixed` (PR comment / report) | Fetches an open GitHub PR diff via `gh`, validates LLM review findings with Pydantic (dropping hallucinated files and sorting by severity), writes `review.md`, and optionally comments on the PR. |
| `create-workflow` | Yes | `workflow-goal` | `fixed` (`workflows/drafts/`) | Generates `CATALOG.md` and example workflows from currently registered plugins, drafts a new workflow YAML, validates and repairs it, attaches security/spend review notes, and saves it under `workflows/drafts/`. |
| `flutter-app-factory` | No (offline demo) | — | `local-git` | Offline end-to-end demonstration using `fixture` LLM replies and simulated `fake` Flutter tool across 4 sample jobs. |
| `java-migration-demo` | No (offline demo) | — | `local-git` | Batch repository migration demo comparing deterministic key updates vs. `scripted` LLM migration and build repair. |
