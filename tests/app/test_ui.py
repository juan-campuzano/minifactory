from rich.console import Console

from minifactory.cli.ui import LiveBoard
from minifactory.core.models import Artifact, JobResult


def feed(board, job, *statuses):
    board({"type": "job_started", "job": job})
    for s in statuses:
        board({"type": "step_finished", "job": job, "status": s})
    board({"type": "llm_call", "job": job, "input_tokens": 1000, "output_tokens": 200, "cost_usd": 0.0012})


def test_board_and_summary_render():
    console = Console(record=True, width=100, force_terminal=False)
    board = LiveBoard(["app_a", "app_b"], ["plan", "build", "ship"], console)
    feed(board, "app_a", "ok", "ok", "ok")
    board({"type": "job_finished", "job": "app_a", "outcome": "succeeded"})
    feed(board, "app_b", "ok", "failed")
    board({"type": "job_finished", "job": "app_b", "outcome": "failed"})

    console.print(board.render())
    results = [
        JobResult(job_id="app_a", outcome="succeeded", notes=["coverage 50%"],
                  artifacts=[Artifact(kind="pull_request", ref="local://app_a/pr/1")]),
        JobResult(job_id="app_b", outcome="failed", reason="build: boom"),
    ]
    board.summary(results)
    out = console.export_text()
    assert "app_a" in out and "● ● ●" in out and "● ✗ ○" in out
    assert "local://app_a/pr/1" in out and "coverage 50%" in out and "build: boom" in out
    assert "2,400 in" not in out and "2,000 in / 400 out" in out and "$0.0024" in out


def test_running_step_name_is_shown_with_elapsed_time():
    console = Console(record=True, width=100, force_terminal=False)
    board = LiveBoard(["app_a"], ["plan", "build", "ship"], console)
    board({"type": "job_started", "job": "app_a"})
    board({"type": "step_finished", "job": "app_a", "status": "ok"})
    board({"type": "step_started", "job": "app_a", "step": "build"})
    console.print(board.render())
    out = console.export_text()
    job_row = next(line for line in out.splitlines() if line.startswith("│ app_a"))
    assert "build" in job_row and "0s" in job_row  # the `now` cell: running step + elapsed
    assert "plan → build → ship" in out  # the full flow stays visible
