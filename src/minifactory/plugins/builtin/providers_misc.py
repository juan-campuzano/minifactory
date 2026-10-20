"""Secrets, target sources and executors."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

import yaml

from minifactory.core.models import Job, JobResult
from minifactory.core.registry import register


@register("secrets", "env")
class EnvSecrets:
    def get(self, name: str) -> str:
        try:
            return os.environ[name]
        except KeyError:
            raise KeyError(f"secret '{name}' is not set in the environment") from None


# -- target sources: "what should we work on?" (your Neptune query lives here) ----------
@register("source", "static")
class StaticSource:
    def __init__(self, jobs: list[dict[str, Any]]):
        self._jobs = jobs

    def jobs(self) -> list[Job]:
        return [Job(id=j["name"], name=j["name"], attrs=j) for j in self._jobs]


@register("source", "catalog")
class CatalogSource:
    """Reads a JSON catalog and keeps entries whose `field` is below a threshold, the
    local equivalent of 'microservices below the target Java version'."""

    def __init__(self, path: str, below: int, field: str = "java_version"):
        self.path, self.below, self.field = Path(path), below, field

    def jobs(self) -> list[Job]:
        entries = json.loads(self.path.read_text())
        return [Job(id=e["name"], name=e["name"], attrs=e)
                for e in entries if int(e[self.field]) < self.below]


@register("source", "app-specs")
class AppSpecSource:
    """One job per `*.yaml` spec in a directory: the 'what apps should we build?' queue.
    A spec needs `name` (also the repo name) and `description`; `features` is optional."""

    def __init__(self, path: str):
        self.path = Path(path)

    def jobs(self) -> list[Job]:
        specs = [yaml.safe_load(f.read_text()) for f in sorted(self.path.glob("*.yaml"))]
        return [Job(id=s["name"], name=s["name"], attrs=s) for s in specs]


# -- executors: "where do jobs run?" (an AWS Batch executor would implement the same port)
@register("executor", "local")
class LocalExecutor:
    def run(self, jobs: list[Job], fn: Callable[[Job], JobResult]) -> list[JobResult]:
        return [fn(j) for j in jobs]


@register("executor", "threads")
class ThreadExecutor:
    def __init__(self, workers: int = 4):
        self.workers = workers

    def run(self, jobs: list[Job], fn: Callable[[Job], JobResult]) -> list[JobResult]:
        with ThreadPoolExecutor(self.workers) as pool:
            return list(pool.map(fn, jobs))
