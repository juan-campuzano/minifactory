"""SCM provider for GitHub, built on the `gh` CLI (so it reuses your `gh auth login`; no token
is read or stored by the factory) plus plain git."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from factory.core.registry import register

from .util import commit_all, git

# (argv, cwd) -> (returncode, stdout, stderr). Injectable so tests never touch GitHub.
Runner = Callable[[list[str], Path | None], tuple[int, str, str]]


def _subprocess_runner(argv: list[str], cwd: Path | None) -> tuple[int, str, str]:
    p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


@register("scm", "github")
class GitHub:
    """New projects become new GitHub repos (`init_repo`, private by default, with an initial
    README commit on the default branch); the generated code arrives as a PR from a branch."""

    delivery_kind = "pull_request"
    # Use gh's own token for git pushes, whatever credential helper the machine has configured.
    _PUSH_AUTH = ("-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential")

    def __init__(self, owner: str | None = None, private: bool = True, runner: Runner | None = None):
        self._owner, self.private = owner, private
        self._run = runner or _subprocess_runner

    def _gh(self, *args: str, cwd: Path | None = None) -> str:
        rc, out, err = self._run(["gh", *args], cwd)
        if rc != 0:
            raise RuntimeError(f"gh {' '.join(args[:3])} failed: {err or out}")
        return out

    @property
    def owner(self) -> str:
        if not self._owner:
            self._owner = self._gh("api", "user", "--jq", ".login")
        return self._owner

    def _full(self, repo: str) -> str:
        return f"{self.owner}/{repo}"

    def target(self, repo: str) -> str:
        return f"github.com/{self._full(repo)} ({'private' if self.private else 'PUBLIC'})"

    def _exists(self, repo: str) -> bool:
        return self._run(["gh", "repo", "view", self._full(repo)], None)[0] == 0

    def init_repo(self, repo: str, dest: Path) -> None:
        if self._exists(repo):
            raise FileExistsError(f"GitHub repository {self._full(repo)} already exists")
        self._gh("repo", "create", self._full(repo), "--private" if self.private else "--public",
                 "--add-readme")
        self._gh("repo", "clone", self._full(repo), str(dest))

    def default_branch(self, repo: str) -> str:
        return self._gh("repo", "view", self._full(repo), "--json", "defaultBranchRef",
                        "--jq", ".defaultBranchRef.name")

    def clone(self, repo: str, dest: Path, branch: str | None = None) -> None:
        self._gh("repo", "clone", self._full(repo), str(dest))
        if branch:
            git("checkout", branch, cwd=dest)

    def branch_exists(self, repo: str, branch: str) -> bool:
        rc, _, err = self._run(["gh", "api", f"repos/{self._full(repo)}/branches/{branch}"], None)
        if rc == 0:
            return True
        if "404" in err or "Not Found" in err:  # repo or branch missing
            return False
        raise RuntimeError(f"gh api failed: {err}")

    def open_prs(self, repo: str) -> list[dict[str, Any]]:
        if not self._exists(repo):
            return []
        rows = json.loads(self._gh("pr", "list", "--repo", self._full(repo), "--state", "open",
                                   "--json", "headRefName,number,url"))
        return [{"branch": r["headRefName"], "number": r["number"], "url": r["url"]} for r in rows]

    def push_and_open_pr(self, repo: str, workdir: Path, branch: str, title: str,
                         body: str) -> str | None:
        git("checkout", "-B", branch, cwd=workdir)
        commit_all(workdir, title)
        base = self.default_branch(repo)
        if int(git("rev-list", "--count", f"origin/{base}..HEAD", cwd=workdir)) == 0:
            return None
        git(*self._PUSH_AUTH, "push", "--quiet", "-u", "origin", branch, cwd=workdir)
        url = self._gh("pr", "create", "--repo", self._full(repo), "--base", base, "--head", branch,
                       "--title", title, "--body", body)
        return url.splitlines()[-1]
