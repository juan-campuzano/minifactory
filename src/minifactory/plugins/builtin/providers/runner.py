"""Runners: how a command is executed (see core/ports.Runner)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from minifactory.core.registry import register

from ..support.env import filtered
from ..support.shell import run_shell


@register("runner", "host")
class HostRunner:
    """Runs commands on this machine, as your user, with a FILTERED environment.

    `env: minimal` (default): only what a command needs to find its tools and reach the network; no AWS keys, API
    keys or tokens. `pass_env: [NAME, PREFIX_*]` adds variables on purpose. `env: inherit` is the old behaviour
    (everything). This hides variables, not files: `~/.aws` and `~/.ssh` stay readable;
    that needs a sandboxed runner."""

    def __init__(self, env: Literal["minimal", "inherit"] = "minimal", pass_env: list[str] | None = None):
        if env not in ("minimal", "inherit"):
            raise ValueError(f"runner env must be 'minimal' or 'inherit', got {env!r}")
        self.env, self.pass_env = env, list(pass_env or [])

    def run(self, cmd: str, cwd: Path, timeout: int = 120) -> tuple[int, str]:
        if self.env == "inherit":
            return run_shell(cmd, cwd, timeout, env=dict(os.environ))
        return run_shell(cmd, cwd, timeout, env=filtered(os.environ, self.pass_env))
