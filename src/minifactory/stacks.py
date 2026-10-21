"""Stack profiles: everything language-specific, as data. A profile says how to recognise a stack,
how to scaffold a project, which commands analyse and test it, where code and tests live and what an
LLM should know about its idioms. Steps and workflows stay language-agnostic and read the profile.

Profiles are YAML files: the packaged ones (`minifactory/profiles/`) and your own in `<workspace>/stacks/`
(a workspace profile with the same name wins). Add a stack by adding a file, no code."""

from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .core.errors import FactoryError

PROFILES_DIR = Path(__file__).parent / "profiles"
WORKSPACE_DIR = "stacks"


class StackError(FactoryError):
    pass


class StackProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-z][a-z0-9-]{0,30}$")
    description: str
    requires: list[str] = Field(default_factory=list)  # executables that must be on PATH
    detect: list[str] = Field(default_factory=list)  # files whose presence identifies an existing repo
    manifest: str = ""  # the dependency/project file (shown to the LLM, reviewed for new dependencies)
    seed_files: dict[str, str] = Field(default_factory=dict)  # path -> content, written by scaffold
    scaffold: list[str] = Field(default_factory=list)  # shell commands run after seeding
    # analyze, test, test_files (takes {paths}), format, setup; a missing one means "not applicable"
    commands: dict[str, str] = Field(default_factory=dict)
    source_globs: list[str]
    test_globs: list[str]
    test_prefixes: list[str]  # where tests live: a reproduction test may only be written there
    repro_test_path: str
    file_example: list[str]  # example paths shown to the planner (so it follows this stack's layout)
    hints: str = ""  # always true of this stack (how its tests are written): shown for new AND existing projects
    new_project_hints: str = ""  # layout/constraints for a NEW project only
    broken_test_patterns: list[str] = Field(default_factory=list)  # output that means "the test did not run"

    @property
    def context_globs(self) -> list[str]:
        """What an agent should see: the sources, the tests and the manifest."""
        return [*self.source_globs, *self.test_globs, *([self.manifest] if self.manifest else [])]


def _load(path: Path) -> StackProfile:
    try:
        return StackProfile.model_validate(yaml.safe_load(path.read_text()))
    except (OSError, yaml.YAMLError, ValidationError) as e:
        raise StackError(f"cannot load stack profile {path}: {e}") from None


def available(workspace_root: Path | None = None) -> dict[str, StackProfile]:
    """Packaged profiles, then the workspace's `stacks/*.yaml` (which win by name)."""
    found: dict[str, StackProfile] = {}
    folders = [PROFILES_DIR, (workspace_root or Path.cwd()) / WORKSPACE_DIR]
    for folder in folders:
        for path in sorted(folder.glob("*.yaml")):
            profile = _load(path)
            found[profile.name] = profile
    return found


def get(name: str | None, workspace_root: Path | None = None) -> StackProfile:
    profiles = available(workspace_root)
    if not name:
        raise StackError(f"no stack given. Available: {', '.join(profiles)}")
    if name not in profiles:
        raise StackError(f"unknown stack '{name}'. Available: {', '.join(profiles)}")
    return profiles[name]


def detect(repo_dir: Path, workspace_root: Path | None = None) -> list[str]:
    """Names of every stack whose `detect` files exist in the repository (several = ambiguous)."""
    return [p.name for p in available(workspace_root).values() if any((repo_dir / f).exists() for f in p.detect)]


def guidance(profile: StackProfile, name: str, *, new_project: bool) -> str:
    """What to tell the LLM about this stack. Layout rules apply only to projects we create: in an
    existing repository the code already decided its own layout and dependencies."""
    parts = [profile.hints, profile.new_project_hints if new_project else ""]
    return f"STACK: {profile.name}\n" + render("\n".join(p.strip() for p in parts if p.strip()), name=name) + "\n"


def project_name(raw: str) -> str:
    """A name that is valid as a package/module/artifact in every stack: lower snake case."""
    name = re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")
    return name if re.match(r"[a-z]", name) else f"app_{name}"


def render(text: str, *, name: str = "", paths: list[str] | None = None) -> str:
    """Fill the profile placeholders. Plain replacement, not str.format: shell scripts are full of braces."""
    return (text.replace("{python}", shlex.quote(sys.executable))
                .replace("{name}", name)
                .replace("{pkg}", name.replace("_", ""))
                .replace("{paths}", " ".join(shlex.quote(p) for p in (paths or []))))
