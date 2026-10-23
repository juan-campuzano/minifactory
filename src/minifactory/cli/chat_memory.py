"""What `minifactory chat` remembers during one conversation: the requests that reached a drafted input, whether they
ran, how they ended, and the repository / pull request they were about. Memory only fills in what a request leaves
out, and only after the request failed for lacking it; what it filled is shown, and the confirmation of `ask` still
shows the drafted input before anything runs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from minifactory.core.models import Job, JobResult

_REPO_WORD = re.compile(r"(?<![\w/.-])[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?![\w/-])")
_PR_WORD = re.compile(r"\b(?:pr|pull request|pull)\b", re.IGNORECASE)
_HAS_NUMBER = re.compile(r"#\s*\d+|\b(?:pr|pull request|pull)\s*#?\s*\d+", re.IGNORECASE)


@dataclass
class Turn:
    workflow: str
    job: Job
    at: str = field(default_factory=lambda: datetime.now().strftime("%H:%M"))
    outcome: str = "not run"  # not run | succeeded | failed | discarded
    detail: str = ""  # an artifact (PR, folder) or the reason it did not finish
    report: str = ""  # the text a review produced, if any


@dataclass
class Session:
    turns: list[Turn] = field(default_factory=list)

    def drafted(self, workflow: str, job: Job) -> None:
        self.turns.append(Turn(workflow, job))

    def finished(self, results: list[JobResult]) -> None:
        if not self.turns or not results:
            return
        result, turn = results[0], self.turns[-1]
        turn.outcome = result.outcome
        turn.detail = result.artifacts[0].ref if result.artifacts else result.reason
        for record in result.steps:
            if isinstance(record.outputs.get("report"), str):
                turn.report = record.outputs["report"]

    def _last(self, key: str) -> str | int | None:
        return next((t.job.attrs[key] for t in reversed(self.turns) if t.job.attrs.get(key)), None)

    def fill(self, request: str) -> tuple[str, str]:
        """The request completed with the last repository (and pull request number) when it names none.
        Returns (request, what was added); the same request and "" when there is nothing to add."""
        repo, number = self._last("repo"), self._last("pr")
        added = []
        out = request
        if repo and not _REPO_WORD.search(request):
            out += f" in {repo}"
            added.append(str(repo))
            if number and _PR_WORD.search(request) and not _HAS_NUMBER.search(request):
                out += f" (#{number})"
                added.append(f"#{number}")
        return out, " ".join(added)

    def forget(self) -> None:
        self.turns.clear()

    def lines(self) -> list[str]:
        return [f"{i}. {t.at}  {t.workflow:<12} {t.job.name:<28} {t.outcome:<10} {t.detail}".rstrip()
                for i, t in enumerate(self.turns, 1)]
