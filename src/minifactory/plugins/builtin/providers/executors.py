"""Executors: "where do jobs run?" (an AWS Batch executor would implement the same port)."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from minifactory.core.models import Job, JobResult
from minifactory.core.registry import register


@register("executor", "local")
class LocalExecutor:
    """Run jobs one after another."""

    def run(self, jobs: list[Job], fn: Callable[[Job], JobResult]) -> list[JobResult]:
        return [fn(j) for j in jobs]


@register("executor", "threads")
class ThreadExecutor:
    """Run up to `workers` jobs in parallel threads."""

    def __init__(self, workers: int = 4):
        self.workers = workers

    def run(self, jobs: list[Job], fn: Callable[[Job], JobResult]) -> list[JobResult]:
        with ThreadPoolExecutor(self.workers) as pool:
            return list(pool.map(fn, jobs))
