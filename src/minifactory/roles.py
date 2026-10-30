"""Role profiles: reusable agent personas, default skills and file-path boundaries, as data.

Packaged roles live in `minifactory/profiles/roles/*.yaml`; a workspace can add or override roles in
`<workspace>/roles/*.yaml`. Any `agent.*` step can take `role: <name>`, which injects the role's persona
and skills into the prompt, enforces its file-path boundaries (`allowed_prefixes`, `forbid_prefixes`,
`tests_only`) on edits, and selects the workflow's role-specific LLM (`llms.<role>`) if one is configured.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .core.errors import FactoryError

PROFILES_DIR = Path(__file__).parent / "profiles" / "roles"
WORKSPACE_DIR = "roles"


class RoleError(FactoryError):
    pass


class RoleProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,30}$")
    description: str
    persona: str
    skills: list[str] = Field(default_factory=list)
    allowed_prefixes: list[str] = Field(default_factory=list)
    forbid_prefixes: list[str] = Field(default_factory=list)
    tests_only: bool = False


def _load(path: Path) -> RoleProfile:
    try:
        return RoleProfile.model_validate(yaml.safe_load(path.read_text()))
    except (OSError, yaml.YAMLError, ValidationError) as e:
        raise RoleError(f"cannot load role profile {path}: {e}") from None


def available(workspace_root: Path | None = None) -> dict[str, RoleProfile]:
    """Packaged roles, then the workspace's `roles/*.yaml` (which win by name)."""
    found: dict[str, RoleProfile] = {}
    folders = [PROFILES_DIR, (workspace_root or Path.cwd()) / WORKSPACE_DIR]
    for folder in folders:
        for path in sorted(folder.glob("*.yaml")):
            profile = _load(path)
            found[profile.name] = profile
    return found


def get(name: str | None, workspace_root: Path | None = None) -> RoleProfile:
    profiles = available(workspace_root)
    if not name:
        raise RoleError(f"no role given. Available: {', '.join(profiles)}")
    if name not in profiles:
        raise RoleError(f"unknown role '{name}'. Available: {', '.join(profiles)}")
    return profiles[name]


def prompt_block(role: RoleProfile) -> str:
    """The prompt text describing this role's perspective and rules."""
    return f"ROLE: {role.name} ({role.description})\n{role.persona.strip()}\n"
