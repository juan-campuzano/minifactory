"""Where a user's workflows live. Code ships in the package; content lives in a *workspace*:

    my-factory/
      minifactory.yaml        config (all keys optional)
      workflows/          the user's workflows (routable by `minifactory ask`)
      specs/ ...          whatever the workflows reference, relative to this directory

Lookup, like git: the nearest `minifactory.yaml` going up from the current directory; otherwise a
global workspace in `$XDG_CONFIG_HOME/minifactory` (default `~/.config/minifactory`). With neither,
commands that accept a file path still work from the current directory."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from .core.errors import FactoryError

CONFIG_NAME = "minifactory.yaml"


class ConfigError(FactoryError):
    pass


class FactoryConfig(BaseModel):
    """Every key is optional; a CLI flag beats the config, the config beats these defaults."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    workflows_dir: str = "workflows"
    runs_dir: str = ".minifactory/runs"
    output_dir: str = "output"
    router: str = "jev"
    threshold: float = 0.7
    plugins: list[str] = []


@dataclass(frozen=True)
class Workspace:
    root: Path
    config: FactoryConfig
    is_global: bool = False

    @property
    def workflow_dirs(self) -> list[Path]:
        """User workflow folders, most specific first: the project's, then the global one."""
        dirs = [self.root / self.config.workflows_dir]
        user = global_dir() / "workflows"
        if not self.is_global and user.is_dir():
            dirs.append(user)
        return dirs


def global_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "minifactory"


def load(root: Path, is_global: bool = False) -> Workspace:
    path = root / CONFIG_NAME
    try:
        data = yaml.safe_load(path.read_text()) if path.is_file() else {}
        return Workspace(root, FactoryConfig.model_validate(data or {}), is_global)
    except (OSError, yaml.YAMLError, ValidationError) as e:
        raise ConfigError(f"cannot load {path}: {e}") from None


def find(start: Path | None = None) -> Workspace | None:
    here = (start or Path.cwd()).resolve()
    for folder in (here, *here.parents):
        if (folder / CONFIG_NAME).is_file():
            return load(folder)
    home = global_dir()
    if (home / CONFIG_NAME).is_file() or (home / "workflows").is_dir():
        return load(home, is_global=True)
    return None


_CONFIG_TEMPLATE = """\
# minifactory workspace. Every key is optional; command-line flags override these.
schema_version: 1
# workflows_dir: workflows      # your workflows (the ones `minifactory ask` can choose from)
# runs_dir: .minifactory/runs       # per-job state, events and work directories
# output_dir: output            # parent folder for `--output local`
# router: jev                   # needs TYPESAFE_API_KEY; `keyword` works offline
# threshold: 0.7                # minimum router confidence to act without asking
# plugins: []                   # extra python modules that register plugins
"""


def init(folder: Path) -> list[str]:
    """Create a workspace in `folder`. Idempotent: existing files are never touched."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "workflows").mkdir(exist_ok=True)
    created = []
    for name, content in ((CONFIG_NAME, _CONFIG_TEMPLATE), (".gitignore", ".minifactory/\noutput/\n")):
        target = folder / name
        if not target.exists():
            target.write_text(content)
            created.append(name)
    return created
