from __future__ import annotations

import json
import os
import re
import ssl
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


def run_shell(cmd: str, cwd: Path, timeout: int = 120) -> tuple[int, str]:
    # Commands may do `python -m minifactory...`; make that work without an installed package.
    src_root = Path(__file__).resolve().parents[3]
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


# -- the (very small) protocol between agent steps and the LLM -------------------------
SYSTEM_PROMPT = (
    "You are an automated code-migration agent. Reply ONLY with edits, no explanations and no "
    "markdown code fences. For a new or small file, give its full content:\n"
    "FILE: <relative path>\n<entire new file content>\nEND_FILE\n"
    "For an existing file, prefer small exact edits (the SEARCH text must appear exactly once):\n"
    "PATCH: <relative path>\n<<<<<<< SEARCH\n<exact existing text>\n=======\n<new text>\n"
    ">>>>>>> REPLACE\nEND_PATCH"
)
_EDIT = re.compile(r"FILE: (\S+)\n(.*?)\nEND_FILE", re.DOTALL)


def file_blocks(repo_dir: Path, files: list[str]) -> str:
    out = []
    for rel in files:
        path = safe_path(repo_dir, rel)
        if path.exists():
            out.append(f"=== FILE {rel} ===\n{path.read_text().rstrip()}\n=== END ===\n")
    return "\n".join(out)


def collect_files(repo_dir: Path, files: list[str], globs: list[str],
                  max_chars: int = 60_000) -> list[str]:
    """Explicit `files` first, then glob matches, stopping once the context budget is spent.

    Globs must stay inside the repo; explicit files are always included."""
    found = dict.fromkeys(files)
    used = sum(len(safe_path(repo_dir, f).read_text()) for f in files if safe_path(repo_dir, f).exists())
    for pattern in globs:
        if pattern.startswith("/") or ".." in Path(pattern).parts:
            raise ValueError(f"glob must be relative and stay inside the repository: {pattern}")
        for path in sorted(repo_dir.glob(pattern)):
            rel = path.relative_to(repo_dir).as_posix()
            if not path.is_file() or rel in found:
                continue
            used += len(path.read_text())
            if used > max_chars:
                return list(found)
            found[rel] = None
    return list(found)


_FENCED = re.compile(r"\A\s*```[\w+-]*\n(.*?)\n```\s*\Z", re.DOTALL)


def parse_edits(reply: str) -> dict[str, str]:
    """Parse FILE/END_FILE blocks. Models often wrap the content in a markdown fence anyway,
    so a single enclosing fence is stripped."""
    return {m.group(1): _FENCED.sub(r"\1", m.group(2)) for m in _EDIT.finditer(reply)}


def apply_edits(repo_dir: Path, edits: dict[str, str]) -> list[str]:
    for rel, content in edits.items():
        path = safe_path(repo_dir, rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.rstrip("\n") + "\n")
    return sorted(edits)


def first_json_object(text: str) -> object:
    """Models often wrap JSON in prose or code fences, or add chatter after it:
    take the first complete JSON object and ignore the rest."""
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in the reply")
    return json.JSONDecoder().raw_decode(text[start:])[0]


def ssl_context() -> ssl.SSLContext:
    """TLS context for our HTTP providers. python.org builds on macOS ship without root
    certificates (CERTIFICATE_VERIFY_FAILED), so prefer certifi's bundle when it is installed."""
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


# -- exact-match patches: how an agent edits a file it did not write -----------------------
class PatchError(ValueError):
    """A patch that cannot be applied exactly; nothing is written when this is raised."""


_PATCH = re.compile(r"PATCH: (\S+)\n(.*?)\nEND_PATCH", re.DOTALL)
_HUNK = re.compile(r"<<<<<<< SEARCH\n(.*?)\n?=======\n(.*?)\n?>>>>>>> REPLACE", re.DOTALL)


def parse_patches(reply: str) -> dict[str, list[tuple[str, str]]]:
    """path -> [(search, replace), ...] in order. An empty SEARCH means 'create this file'."""
    out: dict[str, list[tuple[str, str]]] = {}
    for m in _PATCH.finditer(reply):
        hunks = [(h.group(1), h.group(2)) for h in _HUNK.finditer(m.group(2))]
        if hunks:
            out.setdefault(m.group(1), []).extend(hunks)
    return out


def apply_patches(repo_dir: Path, patches: dict[str, list[tuple[str, str]]]) -> list[str]:
    """All-or-nothing: every SEARCH must match exactly once in the file as edited so far."""
    results: dict[str, str] = {}
    for rel, hunks in patches.items():
        path = safe_path(repo_dir, rel)
        content = path.read_text() if path.exists() else None
        for search, replace in hunks:
            if not search.strip():
                if content is not None:
                    raise PatchError(f"{rel}: cannot create a file that already exists")
                content = replace
                continue
            if content is None:
                raise PatchError(f"{rel}: file does not exist")
            found = content.count(search)
            if found != 1:
                raise PatchError(f"{rel}: SEARCH text found {found} times (must be exactly 1): "
                                 f"{search.strip().splitlines()[0][:60]!r}")
            content = content.replace(search, replace, 1)
        results[rel] = content or ""
    for rel, content in results.items():
        path = safe_path(repo_dir, rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.rstrip("\n") + "\n")
    return sorted(results)


def apply_reply(repo_dir: Path, reply: str, allowed_prefixes: list[str] | None = None) -> list[str]:
    """Apply FILE blocks (full content) and PATCH blocks (exact edits) from an LLM reply.
    With `allowed_prefixes`, any path outside them is rejected before anything is written."""
    files, patches = parse_edits(reply), parse_patches(reply)
    if allowed_prefixes:
        for rel in [*files, *patches]:
            if not any(rel.startswith(prefix) for prefix in allowed_prefixes):
                raise PatchError(f"{rel}: outside the allowed paths {allowed_prefixes}")
    changed = apply_patches(repo_dir, patches) if patches else []
    changed += apply_edits(repo_dir, files) if files else []
    return sorted(set(changed))
