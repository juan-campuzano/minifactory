---
title: Getting Started
description: Install minifactory, verify your environment with doctor, and run your first offline workflow.
---

`minifactory` is a small engine that runs **declarative workflows** (YAML) made of **plugin steps** over a queue of **jobs**.

## Installation

Python 3.11+ is required. The easiest way to install `minifactory` isolated on your `PATH` is with `uv` or `pipx`:

```bash
uv tool install --prerelease allow minifactory
uv tool install --prerelease allow "minifactory[aws]"   # + boto3, for Amazon Bedrock
```

Or inside a virtual environment with `pip`:

```bash
pip install --pre minifactory
pip install --pre "minifactory[aws]"
```

From a source checkout for development:

```bash
git clone https://github.com/juan-campuzano/minifactory && cd minifactory
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,aws]"
```

## Quick Start (100% Offline, No Keys Needed)

Create a workspace, copy the packaged `flutter-app-factory` offline demo template, validate it, and run it:

```bash
minifactory init my-factory && cd my-factory       # creates minifactory.yaml + workflows/
minifactory workflows list                         # lists packaged templates and workspace workflows
minifactory workflows copy flutter-app-factory     # copies the workflow and sample inputs
minifactory validate flutter-app-factory           # fail-fast validation, runs nothing
minifactory run flutter-app-factory                # runs 4 sample jobs with canned LLM replies
```

The offline demo exercises four execution paths:

| Sample Job | What It Exercises |
|---|---|
| `todo_app` | Happy path: plan, implement, analyze, test, coverage, and PR delivery |
| `counter_needs_repair` | First attempt breaks the build; `agent.repair_build` fixes it automatically |
| `notes_low_coverage` | Non-blocking step (`blocking: false`) annotates the PR without stopping delivery |
| `bad_spec` | Malformed plan JSON fails early at `agent.plan_app` before anything is built |

Each job writes `state.json`, `result.json`, and its working repository under `.minifactory/runs/<workflow>/<job>/`, plus a structured event log in `.minifactory/runs/<workflow>/events.jsonl`.

## Check Your Setup (`minifactory doctor`)

```bash
minifactory doctor                  # toolchains per stack, AWS credentials, gh, router key
minifactory doctor fix-bug          # checks what THIS workflow requires (exits 1 if missing)
minifactory doctor --online         # also verifies live AWS STS and GitHub auth status
```

## Enable Shell Tab Completion

```bash
minifactory completion install      # supports zsh, bash, and fish
minifactory completion status       # installed / stale / missing
```
