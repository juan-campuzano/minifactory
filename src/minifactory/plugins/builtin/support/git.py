"""git, with a fixed author and no terminal prompts."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def git(*args: str, cwd: Path | str | None = None, check: bool = True) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "factory", "GIT_AUTHOR_EMAIL": "factory@localhost",
        "GIT_COMMITTER_NAME": "factory", "GIT_COMMITTER_EMAIL": "factory@localhost",
        "GIT_TERMINAL_PROMPT": "0",
    }
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=env)
    if check and p.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {p.stderr.strip()}")
    return p.stdout.strip() if check else str(p.returncode)


def commit_all(repo_dir: Path, message: str) -> bool:
    if not git("status", "--porcelain", cwd=repo_dir):
        return False
    git("add", "-A", cwd=repo_dir)
    git("-c", "commit.gpgsign=false", "commit", "-m", message, cwd=repo_dir)
    return True
