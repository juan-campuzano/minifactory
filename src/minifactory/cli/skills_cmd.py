"""`minifactory skills add|list`: bring skills (SKILL.md files) into the workspace, after showing what they say.

A source is a local path (a SKILL.md, a skill folder, or a tree with many skills) or a GitHub URL:
    https://github.com/owner/repo                      every SKILL.md in the repository
    https://github.com/owner/repo/tree/main/skills     every SKILL.md under that folder
    https://github.com/owner/repo/blob/main/x/SKILL.md one file
    https://raw.githubusercontent.com/owner/repo/main/x/SKILL.md
A remote source is cloned (shallow) into a temporary folder; nothing in it is executed, and only the SKILL.md
files are copied.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from minifactory import skills, workspace
from minifactory.core.errors import FactoryError
from minifactory.plugins.builtin.support.git import GitError, git


@dataclass(frozen=True)
class Remote:
    clone_url: str
    ref: str | None  # a branch or tag; a ref that contains a slash is not supported in URLs
    subpath: str


def parse_github(source: str) -> Remote:
    url = urlparse(source if "://" in source else f"https://{source}")
    parts = [p for p in url.path.split("/") if p]
    if url.scheme != "https" or url.hostname not in {"github.com", "www.github.com", "raw.githubusercontent.com"} \
            or len(parts) < 2 or ".." in parts:
        raise FactoryError(f"'{source}' is neither a local path nor a GitHub URL "
                           "(https://github.com/owner/repo[/tree/<branch>/<folder>])")
    owner, repo = parts[0], parts[1].removesuffix(".git")
    clone = f"https://github.com/{owner}/{repo}.git"
    rest = parts[2:]
    if url.hostname == "raw.githubusercontent.com":
        return Remote(clone, rest[0] if rest else None, "/".join(rest[1:]))
    if rest and rest[0] in {"tree", "blob"}:
        if len(rest) < 2:
            raise FactoryError(f"'{source}' names no branch after /{rest[0]}/")
        return Remote(clone, rest[1], "/".join(rest[2:]))
    if rest:
        raise FactoryError(f"cannot read '{source}': use the repository, /tree/<branch>/<folder> "
                           "or /blob/<branch>/<file>")
    return Remote(clone, None, "")


def _clone(remote: Remote, into: Path) -> Path:
    args = ["clone", "--quiet", "--depth", "1", *(["--branch", remote.ref] if remote.ref else []),
            remote.clone_url, str(into)]
    try:
        git(*args)
    except (GitError, OSError) as e:
        raise FactoryError(f"could not fetch {remote.clone_url}: {e}") from None
    root = (into / remote.subpath).resolve()
    if not root.is_relative_to(into.resolve()) or not root.exists():
        raise FactoryError(f"'{remote.subpath}' does not exist in {remote.clone_url}")
    return root


def _gather(source: str, scratch: Path) -> tuple[list[skills.Skill], list[str]]:
    local = Path(source).expanduser()
    if local.exists():
        return skills.find_in_tree(local.resolve(), local.resolve().stem if local.is_file() else local.resolve().name)
    remote = parse_github(source)
    root = _clone(remote, scratch / "repo")
    repo = remote.clone_url.rsplit("/", 1)[-1].removesuffix(".git")
    name = (Path(remote.subpath).parent.name if root.is_file() else root.name if remote.subpath else "") or repo
    return skills.find_in_tree(root, name.lower())


def _extra_files(skill: skills.Skill) -> int:
    """Files next to a SKILL.md that will not be copied (scripts, references). Not counted for a repo's top level."""
    folder = skill.path.parent
    if (folder / ".git").exists():
        return 0
    return sum(1 for f in folder.rglob("*") if f.is_file() and f != skill.path and ".git" not in f.parts)


def add(args: argparse.Namespace, ws: workspace.Workspace | None) -> int:
    if ws is None and not args.is_global:
        raise FactoryError("no workspace here. Run `minifactory init` first, or use --global")
    target = workspace.global_dir() / "skills" if args.is_global else Path.cwd() / "skills"
    with tempfile.TemporaryDirectory(prefix="minifactory-skills-") as scratch:
        found, skipped = _gather(args.source, Path(scratch))
        if not found:
            raise FactoryError("no usable SKILL.md in that source" + "".join(f"\n  - {s}" for s in skipped))
        print(f"{len(found)} skill(s) found in {args.source}. They are text that will be added to LLM prompts: "
              "read them before trusting them.")
        todo = []
        for s in found:
            dest = target / s.name / skills.FILE_NAME
            text = s.path.read_text(encoding="utf-8", errors="replace")
            state = ("already installed" if dest.is_file() and dest.read_text(encoding="utf-8") == text
                     else "EXISTS with different content, skipped (remove it first to replace)" if dest.exists()
                     else "new")
            extra = _extra_files(s)
            note = f"\n      ({extra} other file(s) next to it are not copied: only the text is used)" if extra else ""
            print(f"  {s.name:<28} {len(s.body):>6} chars  [{state}]\n      {s.description[:110]}{note}")
            if state == "new":
                todo.append((s, dest, text))
        for line in skipped:
            print(f"  skipped: {line}")
        if not todo:
            print("nothing to add")
            return 0
        if not args.yes and (not sys.stdin.isatty() or input(f"Add {len(todo)} skill(s) to {target}? [y/N] ")
                             .strip().lower() != "y"):
            print("not added (confirm interactively or pass --yes)")
            return 2
        for _, dest, text in todo:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text, encoding="utf-8")
    print(f"added {', '.join(s.name for s, _, _ in todo)}. Use them with `skills: [name]` on an agent.* step")
    return 0


def run_skills(args: argparse.Namespace, ws: workspace.Workspace | None) -> int:
    if args.skills_cmd == "add":
        return add(args, ws)
    have = skills.installed()
    if not have:
        print("no skills installed. Add some with `minifactory skills add <path or GitHub URL>`")
    for s in have.values():
        print(f"  {s.name:<28} {s.description[:80]}\n      {s.path}")
    return 0
