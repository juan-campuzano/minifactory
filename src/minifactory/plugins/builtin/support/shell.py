"""Running commands and confining paths."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def run_shell(cmd: str, cwd: Path, timeout: int = 120) -> tuple[int, str]:
    if not cmd.strip():  # `sh -c ""` exits 0: an empty check would pass anything
        return 2, "refusing to run an empty command"
    # Commands may do `python -m minifactory...`; make that work without an installed package.
    src_root = Path(__file__).resolve().parents[4]
    extra = [str(src_root)] if src_root.name == "src" else []  # only a source checkout needs this
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [*extra, os.environ.get("PYTHONPATH")]))}
    try:
        p = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout, env=env)
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s: {cmd}"


def safe_path(base: Path, rel: str) -> Path:
    """Resolve rel inside base; refuse anything that escapes it (LLM output is untrusted)."""
    path = (base / rel).resolve()
    if base.resolve() not in path.parents and path != base.resolve():
        raise ValueError(f"path escapes the repository: {rel}")
    return path
