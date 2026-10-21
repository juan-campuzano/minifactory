"""Running commands and confining paths."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .env import filtered


def run_shell(cmd: str, cwd: Path, timeout: int = 120, env: Mapping[str, str] | None = None) -> tuple[int, str]:
    """Run `cmd` in a shell. `env` is the COMPLETE environment; None means the default policy (support/env.py:
    only what a command needs to find its tools, never credentials)."""
    if not cmd.strip():  # `sh -c ""` exits 0: an empty check would pass anything
        return 2, "refusing to run an empty command"
    environ = dict(filtered(os.environ) if env is None else env)
    # Commands may do `python -m minifactory...`; make that work without an installed package.
    src_root = Path(__file__).resolve().parents[4]
    extra = [str(src_root)] if src_root.name == "src" else []  # only a source checkout needs this
    python_path = os.pathsep.join(filter(None, [*extra, environ.get("PYTHONPATH")]))
    if python_path:
        environ["PYTHONPATH"] = python_path
    try:
        p = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=environ)
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s: {cmd}"


def run_cmd(ctx: Any, cmd: str, timeout: int = 120, cwd: Path | None = None) -> tuple[int, str]:
    """What steps call: run through the workflow's runner, or with the default policy when the context has none."""
    where = cwd or ctx.repo_dir
    runner = getattr(ctx, "runner", None)
    return run_shell(cmd, where, timeout) if runner is None else runner.run(cmd, where, timeout)


def safe_path(base: Path, rel: str) -> Path:
    """Resolve rel inside base; refuse anything that escapes it (LLM output is untrusted)."""
    path = (base / rel).resolve()
    if base.resolve() not in path.parents and path != base.resolve():
        raise ValueError(f"path escapes the repository: {rel}")
    return path
