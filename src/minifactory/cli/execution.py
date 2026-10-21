"""Running jobs and showing the outcome: the live board on a terminal, plain lines otherwise."""

from __future__ import annotations

import sys

from minifactory.core.engine import Engine
from minifactory.core.events import ConsoleSink, EventBus


def summary(results) -> None:
    print("\n" + "─" * 78)
    print(f"{'JOB':<22} {'OUTCOME':<10} DETAIL")
    for r in results:
        pr = r.artifacts[0].ref if r.artifacts else ""
        detail = pr or r.reason
        print(f"{r.job_id:<22} {r.outcome:<10} {detail}")
        for note in r.notes:
            print(f"{'':<33} note: {note}")
    counts = {o: sum(r.outcome == o for r in results) for o in ("succeeded", "failed", "discarded")}
    print("─" * 78)
    print("  ".join(f"{k}: {v}" for k, v in counts.items()))


def execute(engine: Engine, bus: EventBus, jobs, args) -> None:
    """Run jobs with the live board on a terminal, plain lines otherwise."""

    def run_one(job):
        return engine.run_job(job, resume=getattr(args, "resume", False))

    spec = engine.spec
    if sys.stdout.isatty() and not args.plain:
        from minifactory.cli.ui import LiveBoard, banner

        board = LiveBoard([j.id for j in jobs], [s.id for s in spec.steps])
        banner(board.console)
        board.console.print(f"[bold]{spec.name}[/]  ·  {len(jobs)} job(s)\n")
        bus.subscribe(board)
        with board:
            results = engine.executor.run(jobs, run_one)
        board.summary(results)
        return

    if not getattr(args, "quiet", False):
        bus.subscribe(ConsoleSink())
    print(f"workflow '{spec.name}': {len(jobs)} job(s)")
    results = engine.executor.run(jobs, run_one)
    summary(results)
