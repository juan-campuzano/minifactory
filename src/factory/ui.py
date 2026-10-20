"""The pretty CLI: a live board while jobs run, then a summary. It is only an event
subscriber (like ConsoleSink), so the engine knows nothing about it. `cli.py` falls back to
the plain sinks when stdout is not a terminal or `--plain` is given."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from rich import box
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from .core.models import JobResult

BANNER = r"""
   ┌─┐ ┌─┐        ░▒▓ minifactory ▓▒░
   │ │ │ │  ♨ ♨   plan · build · verify · ship
 ┌─┴─┴─┴─┴──┴─┴─┐
 │ ▪ ▪ ▪ ▪ ▪ ▪ ▪│▶▶▶  ▣ ▣ ▣
 └──●──────────●┘
"""
GLYPH = {"ok": ("●", "green"), "failed": ("✗", "bold red"), "skipped": ("·", "dim"),
         "discarded": ("⊘", "yellow"), "pending": ("○", "dim")}
OUTCOME = {"succeeded": ("✔ succeeded", "bold green"), "failed": ("✘ failed", "bold red"),
           "discarded": ("⊘ discarded", "bold yellow")}


@dataclass
class _Job:
    statuses: list[str] = field(default_factory=list)
    running: bool = False
    outcome: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    llm_calls: int = 0
    current: str = ""  # step running right now (from step_started)
    started_at: float = 0.0
    spinner: Spinner = field(default_factory=lambda: Spinner("dots"))  # one per job, or it never animates


def banner(console: Console) -> None:
    console.print(Text(BANNER, style="bold cyan"))


class LiveBoard:
    """Subscribe it to the EventBus and use it as a context manager around the run."""

    def __init__(self, job_ids: list[str], step_ids: list[str], console: Console | None = None):
        self.console = console or Console()
        self.steps = step_ids
        self.jobs = {j: _Job() for j in job_ids}
        self._lock = threading.Lock()
        self._live = Live(get_renderable=self.render, console=self.console, refresh_per_second=10,
                          transient=False)

    def __enter__(self) -> LiveBoard:
        self._live.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._live.stop()

    def __call__(self, event: dict[str, Any]) -> None:
        job = self.jobs.get(event.get("job", ""))
        if job is None:
            return
        with self._lock:
            kind = event["type"]
            if kind == "job_started":
                job.running = True
            elif kind == "step_started":
                job.current, job.started_at = event["step"], time.monotonic()
            elif kind == "step_finished":
                job.statuses.append(event["status"])
                job.current = ""
            elif kind == "llm_call":
                job.llm_calls += 1
                job.tokens_in += event.get("input_tokens", 0)
                job.tokens_out += event.get("output_tokens", 0)
                job.cost += event.get("cost_usd", 0.0)
            elif kind == "job_finished":
                job.running, job.outcome = False, event["outcome"]

    # -- rendering ------------------------------------------------------------------------
    def _progress(self, job: _Job) -> RenderableType:
        cells = Text()
        for i in range(len(self.steps)):
            status = job.statuses[i] if i < len(job.statuses) else "pending"
            glyph, style = GLYPH[status]
            cells.append(glyph + " ", style=style)
        return cells

    def _current(self, job: _Job) -> RenderableType:
        if job.outcome:
            label, style = OUTCOME[job.outcome]
            return Text(label, style=style)
        if job.running and len(job.statuses) < len(self.steps):
            name = job.current or self.steps[len(job.statuses)]  # between steps: the next one
            label = Text(name, style="bold cyan")
            if job.current:
                label.append(f"  {time.monotonic() - job.started_at:.0f}s", style="dim")
            job.spinner.update(text=label)
            return job.spinner
        return Text("queued", style="dim")

    def render(self) -> RenderableType:
        table = Table(box=box.ROUNDED, header_style="bold magenta", border_style="bright_black",
                      title="[bold]production line[/]", title_justify="left")
        table.add_column("job", no_wrap=True)
        table.add_column("steps")
        table.add_column("now")
        table.add_column("llm", justify="right")
        with self._lock:
            for name, job in self.jobs.items():
                tokens = job.tokens_in + job.tokens_out
                llm = f"{job.llm_calls}×" + (f" {tokens:,}t" if tokens else "") if job.llm_calls else ""
                table.add_row(Text(name, style="bold"), self._progress(job), self._current(job), llm)
        legend = Text("  ".join(f"{g} {k}" for k, (g, _) in GLYPH.items()), style="dim")
        return Group(table, self._flow(), legend)

    def _flow(self) -> Text:
        """All step names in order: running ones bold cyan, finished-by-every-job green, rest dim."""
        with self._lock:
            running = {j.current for j in self.jobs.values() if j.current}
            finished = min((len(j.statuses) for j in self.jobs.values()), default=0)
        flow = Text()
        for i, name in enumerate(self.steps):
            style = "bold cyan" if name in running else "green" if i < finished else "dim"
            flow.append(name, style=style)
            if i < len(self.steps) - 1:
                flow.append(" → ", style="dim")
        return flow

    # -- final summary --------------------------------------------------------------------
    def summary(self, results: list[JobResult]) -> None:
        table = Table(box=box.SIMPLE_HEAVY, header_style="bold", show_edge=False)
        for col in ("job", "outcome", "detail"):
            table.add_column(col)
        for r in results:
            label, style = OUTCOME[r.outcome]
            pr = r.artifacts[0].ref if r.artifacts else ""
            detail = Text(pr or r.reason, style="cyan" if pr else "")
            for note in r.notes:
                detail.append(f"\n⚠ {note}", style="yellow")
            table.add_row(Text(r.job_id, style="bold"), Text(label, style=style), detail)
        counts = {o: sum(r.outcome == o for r in results) for o in OUTCOME}
        tin = sum(j.tokens_in for j in self.jobs.values())
        tout = sum(j.tokens_out for j in self.jobs.values())
        cost = sum(j.cost for j in self.jobs.values())
        totals = Text.assemble(
            (f"✔ {counts['succeeded']} succeeded", "green"), "   ",
            (f"✘ {counts['failed']} failed", "red"), "   ",
            (f"⊘ {counts['discarded']} discarded", "yellow"))
        if tin or tout:
            totals.append(f"\n🤖 {tin:,} in / {tout:,} out tokens", style="dim")
            if cost:
                totals.append(f"  ·  ≈ ${cost:.4f}", style="dim")
        self.console.print(table)
        self.console.print(Panel(totals, border_style="bright_black", expand=False))


def show_decision(console: Console, decision: Any, threshold: float) -> None:
    """The router's judgment as a small table of probabilities (the 'why' behind the choice)."""
    table = Table(box=box.SIMPLE, header_style="bold", title="router decision", title_justify="left")
    table.add_column("workflow")
    table.add_column("probability", justify="right")
    for name, prob in sorted(decision.probabilities.items(), key=lambda kv: kv[1], reverse=True):
        mark = "→ " if name == decision.choice else "  "
        table.add_row(Text(mark + name, style="bold green" if name == decision.choice else ""), f"{prob:.0%}")
    console.print(table)
    ok = decision.confidence >= threshold
    console.print(Text.assemble(
        "confidence ", (f"{decision.confidence:.2f}", "green" if ok else "red"), f" (threshold {threshold})   ",
        "actionable ", ("yes", "green") if decision.actionable else ("no", "red")))


def show_spec(console: Console, workflow: str, job: Any) -> None:
    body = Text()
    for key, value in job.attrs.items():
        body.append(f"{key}: ", style="bold")
        body.append((", ".join(value) if isinstance(value, list) else str(value)) + "\n")
    console.print(Panel(body, title=f"[bold]{workflow}[/] · drafted input", border_style="cyan", expand=False))
