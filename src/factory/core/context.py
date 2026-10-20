"""What a step receives (StepContext) and what a step is (Step)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, ClassVar

from pydantic import BaseModel, ConfigDict

from .models import Job, StepResult


class StrictParams(BaseModel):
    """Base for step parameters: unknown keys are errors, so YAML typos fail fast."""

    model_config = ConfigDict(extra="forbid")


@dataclass
class StepContext:
    job: Job
    work_dir: Path
    scm: Any  # SCMProvider | None
    llm: Any  # LLMProvider | None
    secrets: Any  # SecretsProvider
    emit: Callable[..., None]
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)  # step id -> outputs
    notes: list[str] = field(default_factory=list)

    @property
    def repo_dir(self) -> Path:
        return self.work_dir / "repo"


class Step:
    """Subclass, set Params, implement run(), and register with @register("step", "x.y")."""

    Params: ClassVar[type[BaseModel]] = StrictParams
    needs: ClassVar[tuple[str, ...]] = ()  # providers required: "scm", "llm"

    def run(self, ctx: StepContext, params: Any) -> StepResult:  # pragma: no cover
        raise NotImplementedError
