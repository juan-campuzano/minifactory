"""Engine behaviour, using plugins defined *here* (outside the core) to show that adding
a step needs no change to the factory."""

from pathlib import Path

from minifactory.core import registry
from minifactory.core.context import Step, StrictParams
from minifactory.core.engine import Engine
from minifactory.core.models import StepResult
from minifactory.core.workflow import WorkflowSpec, validate_spec

registry.load_plugins()
CALLS: list[str] = []


class P(StrictParams):
    label: str = ""
    fail_times: int = 0


@registry.register("step", "t.record")
class Record(Step):
    Params = P

    def run(self, ctx, p):
        CALLS.append(f"{ctx.job.id}:{p.label}")
        return StepResult.ok(label=p.label)


@registry.register("step", "t.fail")
class Fail(Step):
    Params = P

    def run(self, ctx, p):
        return StepResult.failed("boom\nsecond line")


@registry.register("step", "t.flaky")
class Flaky(Step):
    """Fails until its marker file has seen `fail_times` attempts."""

    Params = P

    def run(self, ctx, p):
        marker = ctx.work_dir / "attempts"
        n = int(marker.read_text()) + 1 if marker.exists() else 1
        marker.write_text(str(n))
        return StepResult.ok() if n > p.fail_times else StepResult.failed(f"attempt {n}")


@registry.register("step", "t.crash")
class Crash(Step):
    def run(self, ctx, p):
        raise RuntimeError("plugin bug")


def make(steps, tmp_path, jobs=("j1",)):
    spec = WorkflowSpec.model_validate({
        "name": "t",
        "source": {"use": "static", "with": {"jobs": [{"name": j, "flag": "x"} for j in jobs]}},
        "steps": steps,
    })
    validate_spec(spec)
    return Engine(spec, tmp_path / "runs"), spec


def run(steps, tmp_path, **kw):
    CALLS.clear()
    engine, _ = make(steps, tmp_path)
    return engine.run_job(engine.source.jobs()[0], **kw), engine


def test_happy_path_and_when_skip(tmp_path):
    result, _ = run([
        {"id": "a", "use": "t.record", "with": {"label": "a"}},
        {"id": "b", "use": "t.record", "when": "job.flag == 'nope'"},
        {"id": "c", "use": "t.record", "when": "steps.a.outputs.label == 'a'", "with": {"label": "c"}},
    ], tmp_path)
    assert result.outcome == "succeeded"
    assert [s.status for s in result.steps] == ["ok", "skipped", "ok"]
    assert CALLS == ["j1:a", "j1:c"]


def test_on_fail_policies(tmp_path):
    r, _ = run([{"id": "x", "use": "t.fail"}, {"id": "y", "use": "t.record"}], tmp_path)
    assert (r.outcome, r.reason) == ("failed", "x: boom") and CALLS == []

    r, _ = run([{"id": "x", "use": "t.fail", "on_fail": "discard"}, {"id": "y", "use": "t.record"}], tmp_path)
    assert r.outcome == "discarded" and CALLS == []

    r, _ = run([{"id": "x", "use": "t.fail", "on_fail": "continue"},
                {"id": "y", "use": "t.record", "when": "steps.x.status == 'failed'"}], tmp_path)
    assert r.outcome == "succeeded" and CALLS == ["j1:"]


def test_non_blocking_failure_becomes_a_note(tmp_path):
    r, _ = run([{"id": "x", "use": "t.fail", "blocking": False}, {"id": "y", "use": "t.record"}], tmp_path)
    assert r.outcome == "succeeded"
    assert r.notes == ["non-blocking step 'x' failed: boom"]


def test_plugin_crash_is_contained(tmp_path):
    r, _ = run([{"id": "x", "use": "t.crash"}], tmp_path)
    assert r.outcome == "failed" and "RuntimeError: plugin bug" in r.reason


def test_resume_skips_completed_steps(tmp_path):
    steps = [
        {"id": "a", "use": "t.record", "with": {"label": "a"}},
        {"id": "b", "use": "t.flaky", "with": {"fail_times": 1}},
        {"id": "c", "use": "t.record", "with": {"label": "c"}},
    ]
    r1, engine = run(steps, tmp_path)
    assert r1.outcome == "failed" and CALLS == ["j1:a"]

    CALLS.clear()
    r2 = engine.run_job(engine.source.jobs()[0], resume=True)
    assert r2.outcome == "succeeded"
    assert CALLS == ["j1:c"]  # 'a' was restored from state, not re-run
    assert next(s for s in r2.steps if s.id == "a").outputs == {"label": "a"}


def test_events_are_written(tmp_path):
    _, engine = run([{"id": "a", "use": "t.record"}], tmp_path)
    log = (Path(tmp_path) / "runs" / "t" / "events.jsonl").read_text()
    assert '"type": "step_finished"' in log and '"type": "job_finished"' in log
