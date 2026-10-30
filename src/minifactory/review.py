"""What a person should look at before enabling a workflow someone (or an LLM) wrote: the parts
that run commands, spend money or reach outside the machine. Facts, not a verdict."""

from __future__ import annotations

from dataclasses import dataclass

from .core.workflow import WorkflowSpec

# step -> what it does that a reviewer cares about
_EFFECTS = {
    "scm.open_pr": "pushes a branch and opens a pull request",
    "scm.init_repo": "creates a repository",
    "scm.pr_comment": "posts a public comment on a pull request, as you",
    "file.set_key": "edits a file in the repository",
}
_PROVIDERS = {
    "github": "acts on GitHub as you (through `gh`)",
    "bedrock": "spends Amazon Bedrock tokens",
    "openai": "spends tokens on an OpenAI-compatible endpoint",
}


_PLACEHOLDER_COMMANDS = {"echo", "printf", "true", ":", "sleep"}


@dataclass(frozen=True)
class Finding:
    warn: bool
    text: str

    def __str__(self) -> str:
        return ("! " if self.warn else "· ") + self.text


def review(spec: WorkflowSpec) -> list[Finding]:
    out: list[Finding] = []
    for step in spec.steps:
        if step.use == "shell.run":
            cmd = str(step.with_.get("cmd", ""))
            out.append(Finding(True, f"step '{step.id}' runs a shell command: {cmd!r}"))
            if cmd.split()[:1] and cmd.split()[0] in _PLACEHOLDER_COMMANDS:
                out.append(Finding(True, f"step '{step.id}' only prints text: probably a placeholder standing in "
                                         "for a real action it does not perform"))
        elif step.use in _EFFECTS:
            out.append(Finding(True, f"step '{step.id}' {_EFFECTS[step.use]}"))
        elif step.use.startswith("agent."):
            out.append(Finding(False, f"step '{step.id}' lets an LLM edit files ({step.use})"))
        if "${env." in str(step.with_) and "${env.python}" not in str(step.with_):
            out.append(Finding(True, f"step '{step.id}' reads environment variables"))
    if spec.runner.use == "host" and (spec.runner.with_.get("env") == "inherit" or spec.runner.with_.get("pass_env")):
        how = "inherit your whole environment" if spec.runner.with_.get("env") == "inherit" else (
            f"also see: {', '.join(spec.runner.with_['pass_env'])}")
        out.append(Finding(True, f"runner: commands {how} (credentials included if they match)"))
    for kind, ref in spec.providers.items():
        if ref.use in _PROVIDERS:
            out.append(Finding(ref.use == "github", f"provider {kind}: {ref.use} {_PROVIDERS[ref.use]}"))
    for role_name, ref in spec.llms.items():
        if ref.use in _PROVIDERS:
            out.append(Finding(False, f"llm for role '{role_name}': {ref.use} {_PROVIDERS[ref.use]}"))
    if spec.route is None:
        out.append(Finding(False, "no `route:` block: `minifactory ask` will not be able to choose it"))
    return out
