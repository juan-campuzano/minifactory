"""`minifactory ask`: free text -> the right workflow. This module is the policy; judging is the
router plugin's job (Jev) and drafting the input is the intake plugin's.

Policy lives here, in code, on purpose: confidence says how concentrated the model's answer
is, not whether acting on it is safe."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .core.errors import RoutingError, VagueRequest, WorkflowError
from .core.models import Candidate, Decision
from .core.workflow import PluginRef, WorkflowSpec, load_workflow, validate_spec

DEFAULT_THRESHOLD = 0.7


@dataclass
class Routable:
    path: Path
    spec: WorkflowSpec

    @property
    def candidate(self) -> Candidate:
        r = self.spec.route
        assert r is not None
        return Candidate(name=self.spec.name, description=r.description, not_for=r.not_for,
                         examples=r.examples, needs=r.needs)


def discover(workflows_dirs: str | Path | list[Path]) -> dict[str, Routable]:
    """Workflows with a `route:` block. Folders are searched most specific first (a name found
    earlier wins). A file that fails to load is skipped, so one bad file doesn't hide the rest; it
    only matters (and is reported) when nothing is routable."""
    folders = [Path(d) for d in ([workflows_dirs] if isinstance(workflows_dirs, str | Path) else workflows_dirs)]
    found: dict[str, Routable] = {}
    problems: list[str] = []
    for folder in folders:
        for path in sorted(folder.glob("*.yaml")):
            try:
                spec = load_workflow(path)
            except WorkflowError as e:
                problems.append(str(e))
                continue
            if spec.route and spec.name not in found:
                found[spec.name] = Routable(path, spec)
    if not found:
        detail = f" ({len(problems)} file(s) failed to load: {problems[0]})" if problems else ""
        where = ", ".join(str(f) for f in folders)
        raise RoutingError(f"no workflow in {where} has a `route:` block{detail}. "
                           "Copy one with `minifactory workflows copy NAME` and add a `route:` block")
    return found


def with_output(spec: WorkflowSpec, output: str, *, output_dir: str = "output",
                owner: str | None = None, public: bool = False) -> WorkflowSpec:
    """The workflow, with its `scm` provider replaced by where the user wants the result."""
    if output == "local":
        scm = PluginRef(use="local-dir", **{"with": {"dir": output_dir}})
    elif output == "github":
        options = {"private": not public, **({"owner": owner} if owner else {})}
        scm = PluginRef(use="github", **{"with": options})
    else:
        raise RoutingError(f"unknown output '{output}' (expected local or github)")
    new = spec.model_copy(update={"providers": {**spec.providers, "scm": scm}})
    validate_spec(new)
    return new


def ranked(decision: Decision) -> list[tuple[str, float]]:
    return sorted(decision.probabilities.items(), key=lambda kv: kv[1], reverse=True)


def check(decision: Decision, threshold: float = DEFAULT_THRESHOLD) -> None:
    """Raise RoutingError unless acting on this decision unattended (`--yes`) is justified."""
    if decision.choice is None:
        raise RoutingError("no workflow fits this request")
    if decision.confidence < threshold:
        options = ", ".join(f"{n} {p:.0%}" for n, p in ranked(decision)[:3])
        raise RoutingError(f"not confident enough ({decision.confidence:.2f} < {threshold}): {options}")
    if not decision.actionable:
        raise VagueRequest("the request is too vague for this workflow to start; add details")


