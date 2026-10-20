# Intent Router (`minifactory ask`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (native execution chosen by the user: "si implementa").

**Goal:** `minifactory ask "<free text>"` picks the right workflow (Jev), drafts the job input (LLM), confirms, then runs it.

**Architecture:** workflows declare an optional `route:` block; two new plugin kinds, `router` (jev, keyword) and `intake` (app-spec); a CLI-level orchestrator (`src/minifactory/router.py`) discovers candidates, applies a confidence policy in code and runs the chosen workflow's engine on the drafted `Job`.

**Tech Stack:** Python, pydantic, urllib (Jev HTTP API, no new dependency), existing registry/engine.

**Spec:** the approved design in chat (2026-10-20); decisions: HTTP not SDK, threshold 0.7 configurable, nothing runs without confirmation unless `--yes`, user text is untrusted data.

## Global Constraints
- Core never imports a plugin; new kinds registered in `registry.KINDS`.
- Jev: `POST https://api.typesafe.ai/v1/systemone`, `Authorization: Bearer <TYPESAFE_API_KEY>`, model `jev-latest`; answers: choice `{choice, confidence, probabilities}`, noul `{noul}` (probability of yes), plus `usage`.
- Tests need no network or credentials.
- `--yes` acts only when confident AND actionable; otherwise exit code 2.

## Review Focus
- Request that matches no workflow (`none`) → no execution, explains, exit 2.
- Low confidence → candidates listed with probabilities, no execution.
- Missing `TYPESAFE_API_KEY` → clear error, not a traceback.
- Intake LLM returns invalid/hostile spec (bad name, path traversal chars) → rejected before any run.
- Zero routable workflows → clear error.

### Task 1: Core wiring (kinds, ports, models, `route:` block)
Files: `core/registry.py`, `core/ports.py`, `core/models.py`, `core/workflow.py`; test `tests/test_router.py`.
Produces: `Candidate`, `Decision` models; `Router.choose(request, candidates) -> Decision`; `Intake.build(request, llm) -> Job`; `WorkflowSpec.route: RouteSpec | None` validated (intake must be registered).

### Task 2: Plugins `keyword` router, `jev` router, `app-spec` intake
Files: `plugins/builtin/routers.py`, `plugins/builtin/intakes.py`; tests `tests/test_router.py`, `tests/test_jev.py`.
Produces: `JevRouter(secrets=None, model="jev-latest", transport=None)`, `KeywordRouter()`, `AppSpecIntake()`.

### Task 3: Orchestrator + `minifactory ask`
Files: `src/minifactory/router.py` (`discover`, `decide`, `ask`), `cli.py`; test `tests/test_ask.py`.

### Task 4: Docs and real route metadata
`workflows/flutter-app-factory-bedrock.yaml` gets `route:`; `AGENTS.md`, `docs/plugins.md`, `README.md`.

### Task 5: Live check with the real Jev key (only if `TYPESAFE_API_KEY` is visible).
