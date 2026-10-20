"""Typed data that flows through the factory. Steps never pass loose dicts around."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Status = Literal["ok", "failed", "skipped", "discarded"]
Outcome = Literal["succeeded", "failed", "discarded"]


class Artifact(BaseModel):
    kind: str  # e.g. "pull_request"
    ref: str  # e.g. a URL


class StepResult(BaseModel):
    status: Status = "ok"
    outputs: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[Artifact] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)  # surfaced later (e.g. in the PR body)
    message: str = ""

    @classmethod
    def ok(cls, message: str = "", **outputs: Any) -> "StepResult":
        return cls(status="ok", message=message, outputs=outputs)

    @classmethod
    def failed(cls, message: str, **outputs: Any) -> "StepResult":
        return cls(status="failed", message=message, outputs=outputs)

    @classmethod
    def discarded(cls, message: str) -> "StepResult":
        """Stop this job on purpose: nothing to do / not safe to continue."""
        return cls(status="discarded", message=message)


class Job(BaseModel):
    id: str
    name: str
    attrs: dict[str, Any] = Field(default_factory=dict)


class StepRecord(StepResult):
    id: str
    duration_s: float = 0.0


class JobResult(BaseModel):
    job_id: str
    outcome: Outcome
    reason: str = ""
    steps: list[StepRecord] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class Candidate(BaseModel):
    """A workflow a router may pick. Built from the workflow's `route:` block."""

    name: str
    description: str
    not_for: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    needs: str = ""  # what a request must contain for this workflow to start


class Decision(BaseModel):
    """A router's judgment about a free-text request. `choice` is None for 'no workflow fits'."""

    choice: str | None
    confidence: float
    probabilities: dict[str, float] = Field(default_factory=dict)
    actionable: bool = True  # enough information to start without asking the user
    usage: dict[str, Any] = Field(default_factory=dict)
