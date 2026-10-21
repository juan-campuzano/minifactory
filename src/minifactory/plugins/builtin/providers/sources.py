"""Job sources: "what should we work on?" (a database or API query would live here)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from minifactory.core.models import Job
from minifactory.core.registry import register


@register("source", "static")
class StaticSource:
    """A fixed list of jobs written in the workflow itself (`jobs: [{name: ...}]`)."""

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
