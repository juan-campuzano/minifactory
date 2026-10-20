"""End to end: the demo workflow over six toy repos, each exercising a different path."""

import json
from pathlib import Path

import pytest

from minifactory.core import registry
from minifactory.core.engine import Engine
from minifactory.core.workflow import load_workflow
from minifactory.demo import demo_init

WORKFLOW = (Path(__file__).parent.parent / "src" / "minifactory" / "templates"
            / "java-migration-demo" / "workflow.yaml")
registry.load_plugins()


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # the workflow uses paths relative to the project root
    demo_init("demo")
    engine = Engine(load_workflow(WORKFLOW), tmp_path / "runs")
    return engine, tmp_path


def run_all(engine):
    jobs = engine.source.jobs()
    return {r.job_id: r for r in engine.executor.run(jobs, engine.run_job)}


def test_source_filters_up_to_date_repos(sandbox):
    engine, _ = sandbox
    names = {j.name for j in engine.source.jobs()}
    assert "svc-modern" not in names and len(names) == 5


def test_every_path(sandbox):
    engine, root = sandbox
    results = run_all(engine)
    outcome = {k: v.outcome for k, v in results.items()}
    assert outcome == {
        "svc-clean-ok": "succeeded",
        "svc-other-ok": "succeeded",
        "svc-needs-repair": "succeeded",
        "svc-broken-baseline": "discarded",
        "svc-unfixable": "failed",
    }

    def statuses(job):
        return {s.id: s.status for s in results[job].steps}

    # architecture branching
    assert statuses("svc-clean-ok")["scaffold"] == "ok" and statuses("svc-clean-ok")["llm_migrate"] == "skipped"
    assert statuses("svc-other-ok")["llm_migrate"] == "ok" and statuses("svc-other-ok")["scaffold"] == "skipped"
    # repair loop only when the build is red, and it fixes it
    assert statuses("svc-clean-ok")["repair"] == "skipped"
    assert statuses("svc-needs-repair")["build"] == "failed" and statuses("svc-needs-repair")["repair"] == "ok"
    # gate discards before any change
    assert results["svc-broken-baseline"].reason.startswith("baseline")
    assert "scaffold" not in statuses("svc-broken-baseline")
    # budgets stop the loop
    assert results["svc-unfixable"].reason.startswith("repair: gave up")
    # non-blocking coverage: PR still opens, with a note in its description
    assert results["svc-other-ok"].notes and "coverage" in results["svc-other-ok"].notes[0]
    pr = json.loads((root / "demo/prs/svc-other-ok/1.json").read_text())
    assert "Factory notes" in pr["body"]
    assert not results["svc-clean-ok"].notes
    # no PR for discarded / failed jobs
    assert not (root / "demo/prs/svc-unfixable").exists()
    assert not (root / "demo/prs/svc-broken-baseline").exists()


def test_second_run_is_idempotent(sandbox):
    engine, _ = sandbox
    run_all(engine)
    second = run_all(engine)
    assert second["svc-clean-ok"].outcome == "discarded"
    assert second["svc-clean-ok"].reason.startswith("guard")
