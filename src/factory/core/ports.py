"""Ports: everything environment-specific lives behind these interfaces.

The core only knows these Protocols. Neptune, Azure DevOps, the STS assume-role dance,
AWS Batch... are all *implementations* that plugins register.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Protocol

from .models import Candidate, Decision, Job, JobResult


class SCMProvider(Protocol):
    def default_branch(self, repo: str) -> str: ...
    def clone(self, repo: str, dest: Path, branch: str | None = None) -> None: ...
    def branch_exists(self, repo: str, branch: str) -> bool: ...
    def open_prs(self, repo: str) -> list[dict[str, Any]]: ...
    def push_and_open_pr(
        self, repo: str, workdir: Path, branch: str, title: str, body: str
    ) -> str | None:
        """Return the PR url, or None when there is nothing to deliver."""


class LLMProvider(Protocol):
    def complete(self, system: str, prompt: str) -> str: ...


class SecretsProvider(Protocol):
    def get(self, name: str) -> str: ...


class TargetSource(Protocol):
    def jobs(self) -> list[Job]: ...


class Executor(Protocol):
    def run(self, jobs: list[Job], fn: Callable[[Job], JobResult]) -> list[JobResult]: ...


class Router(Protocol):
    def choose(self, request: str, candidates: list[Candidate]) -> Decision: ...


class Intake(Protocol):
    def build(self, request: str, llm: Any) -> Job:
        """Turn free text into the Job a workflow expects. Raise ValueError if it can't."""
