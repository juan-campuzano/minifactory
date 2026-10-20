"""SCM provider backed by plain local git repos. Same port an AzureDevOps or GitHub
provider would implement; swapping it is a one-line change in the workflow YAML."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from factory.core.registry import register

from .util import commit_all, git


@register("scm", "local-git")
class LocalGit:
    """`remotes_dir/<repo>.git` are the 'remotes'; PRs are JSON files in `prs_dir/<repo>/`."""

    def __init__(self, remotes_dir: str, prs_dir: str):
        self.remotes = Path(remotes_dir).resolve()
        self.prs = Path(prs_dir).resolve()

    def _remote(self, repo: str) -> Path:
        return self.remotes / f"{repo}.git"

    def default_branch(self, repo: str) -> str:
        return git("--git-dir", str(self._remote(repo)), "symbolic-ref", "--short", "HEAD")

    def init_repo(self, repo: str, dest: Path) -> None:
        """Brand-new project: create the bare remote, clone it and push an initial commit.
        Optional capability (not in the SCMProvider Protocol): only creation workflows need it."""
        remote = self._remote(repo)
        if remote.exists():
            raise FileExistsError(f"repository '{repo}' already exists")
        remote.parent.mkdir(parents=True, exist_ok=True)
        git("init", "--bare", "--quiet", "-b", "main", str(remote))
        git("clone", "--quiet", str(remote), str(dest))
        git("checkout", "-B", "main", cwd=dest)
        (dest / "README.md").write_text(f"# {repo}\n")
        commit_all(dest, "chore: initial commit")
        git("push", "--quiet", "-u", "origin", "main", cwd=dest)

    def clone(self, repo: str, dest: Path, branch: str | None = None) -> None:
        args = ["clone", "--quiet"]
        if branch:
            args += ["--branch", branch]
        git(*args, str(self._remote(repo)), str(dest))

    def branch_exists(self, repo: str, branch: str) -> bool:
        return git("ls-remote", "--exit-code", "--heads", str(self._remote(repo)), branch,
                   check=False) == "0"

    def open_prs(self, repo: str) -> list[dict[str, Any]]:
        folder = self.prs / repo
        prs = [json.loads(p.read_text()) for p in sorted(folder.glob("*.json"))] if folder.exists() else []
        return [pr for pr in prs if pr.get("status") == "open"]

    def push_and_open_pr(self, repo: str, workdir: Path, branch: str, title: str,
                         body: str) -> str | None:
        git("checkout", "-B", branch, cwd=workdir)
        if git("status", "--porcelain", cwd=workdir):
            git("add", "-A", cwd=workdir)
            git("-c", "commit.gpgsign=false", "commit", "-m", title, cwd=workdir)
        base = self.default_branch(repo)
        if int(git("rev-list", "--count", f"origin/{base}..HEAD", cwd=workdir)) == 0:
            return None
        git("push", "--quiet", "origin", branch, cwd=workdir)
        folder = self.prs / repo
        folder.mkdir(parents=True, exist_ok=True)
        number = len(list(folder.glob("*.json"))) + 1
        (folder / f"{number}.json").write_text(json.dumps(
            {"number": number, "branch": branch, "base": base, "title": title,
             "body": body, "status": "open"}, indent=2))
        return f"local://{repo}/pr/{number}"


@register("scm", "local-dir")
class LocalDir:
    """The result is a plain git repo in `<dir>/<name>` (work lands on `main`, no branch, no PR),
    ready to open in an IDE. Created from scratch: it cannot clone existing repositories."""

    delivery_kind = "folder"

    def __init__(self, dir: str = "output"):
        self.root = Path(dir).expanduser().resolve()

    def target(self, repo: str) -> str:
        return str(self.root / repo)

    def default_branch(self, repo: str) -> str:
        return "main"

    def clone(self, repo: str, dest: Path, branch: str | None = None) -> None:
        raise NotImplementedError("local-dir only creates new projects (use init_repo)")

    def branch_exists(self, repo: str, branch: str) -> bool:
        return (self.root / repo).exists()  # a folder with that name is "already done"

    def open_prs(self, repo: str) -> list[dict[str, Any]]:
        return []

    def init_repo(self, repo: str, dest: Path) -> None:
        if (self.root / repo).exists():
            raise FileExistsError(f"{self.root / repo} already exists")
        dest.mkdir(parents=True)
        git("init", "--quiet", "-b", "main", cwd=dest)
        (dest / "README.md").write_text(f"# {repo}\n")
        commit_all(dest, "chore: initial commit")

    def push_and_open_pr(self, repo: str, workdir: Path, branch: str, title: str,
                         body: str) -> str | None:
        target = self.root / repo
        if target.exists():
            raise FileExistsError(f"{target} already exists")
        if body:  # there is no PR description in a folder: the README carries it
            with (workdir / "README.md").open("a") as readme:
                readme.write(f"\n{body}\n")
        commit_all(workdir, title)
        if int(git("rev-list", "--count", "HEAD", cwd=workdir)) <= 1:
            return None  # only the initial commit: nothing was generated
        git("clean", "-fdXq", cwd=workdir)  # drop git-ignored build output (build/, coverage/...)
        self.root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(workdir, target)
        return f"file://{target}"
