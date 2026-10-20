"""Steps for changing a repository that already exists (a bug fix, a feature): find the relevant
files, make a bounded edit, and keep the change small. Edits use the exact-match patch protocol
in `util`, so a stale or wrong edit is rejected instead of silently clobbering a file."""

from __future__ import annotations

import fnmatch
import re

from pydantic import Field

from minifactory.core.context import Step, StepContext, StrictParams
from minifactory.core.models import StepResult
from minifactory.core.registry import register

from .util import (
    SYSTEM_PROMPT,
    PatchError,
    apply_reply,
    collect_files,
    commit_all,
    file_blocks,
    first_json_object,
    git,
)

_WORD = re.compile(r"[a-z0-9]{3,}")


def _what_it_said(reply: str) -> str:
    """An explicit `MISSING: ...` line if there is one (the agreed way to decline), else the END of the
    reply, where a refusal states its conclusion."""
    found = re.search(r"^\s*MISSING:.*$", reply, re.MULTILINE)
    return found.group(0).strip() if found else "..." + " ".join(reply.split())[-300:]


class LocateParams(StrictParams):
    task: str  # the bug report or feature request
    globs: list[str] = Field(default_factory=lambda: ["*"])  # which tracked files may be chosen
    max_files: int = 8
    max_tree: int = 400  # how many paths the LLM is shown (the most task-relevant ones if there are more)


@register("step", "agent.locate_files")
class LocateFiles(Step):
    """Select, don't generate: the LLM picks files from the real list of tracked files, and
    anything it names that is not in that list is discarded."""

    Params = LocateParams
    needs = ("llm",)

    def run(self, ctx: StepContext, p: LocateParams) -> StepResult:
        tracked = git("ls-files", cwd=ctx.repo_dir).splitlines()
        tree = [f for f in tracked if any(fnmatch.fnmatch(f, g) for g in p.globs)]
        if not tree:
            return StepResult.failed("no tracked files match the globs")
        if len(tree) > p.max_tree:  # too many to show: keep the paths that share words with the task
            words = set(_WORD.findall(p.task.lower()))
            tree.sort(key=lambda f: -len(words & set(_WORD.findall(f.lower()))))
            tree = sorted(tree[: p.max_tree])
        prompt = (f"TASK: locate\nAPP: {ctx.job.name}\nREQUEST: {p.task}\n\nTRACKED FILES:\n"
                  + "\n".join(f"- {f}" for f in tree)
                  + f'\n\nReply ONLY with JSON: {{"files": ["path", ...]}}: at most {p.max_files} files '
                    "from the list above that are most relevant to the request, most relevant first.")
        try:
            chosen = first_json_object(ctx.llm.complete(SYSTEM_PROMPT, prompt))
            names = chosen["files"] if isinstance(chosen, dict) else []
        except (ValueError, KeyError, TypeError) as e:
            return StepResult.failed(f"could not read the file selection: {e}")
        valid = list(dict.fromkeys(f for f in names if isinstance(f, str) and f in set(tree)))[: p.max_files]
        if not valid:
            return StepResult.failed("the LLM did not select any file that exists in the repository")
        return StepResult.ok(f"{len(valid)} file(s): {', '.join(valid)}", files=valid)


class EditParams(StrictParams):
    instruction: str
    files: list[str] = Field(default_factory=list)  # context: shown to the LLM in full (often a templated list)
    extra_files: list[str] = Field(default_factory=list)  # more context files, added to `files`
    extra: str = ""  # more context, e.g. the output of a failing test (its tail is kept)
    allowed_prefixes: list[str] = Field(default_factory=list)  # e.g. ["test/"]: nothing else may change
    commit_message: str = "chore: automated edit"
    max_context_chars: int = 60_000


@register("step", "agent.edit")
class Edit(Step):
    """One bounded LLM edit: show these files, apply the reply (patches or whole files), commit."""

    Params = EditParams
    needs = ("llm",)

    def run(self, ctx: StepContext, p: EditParams) -> StepResult:
        shown = collect_files(ctx.repo_dir, [*p.files, *p.extra_files], [], p.max_context_chars)
        extra = f"\nADDITIONAL CONTEXT:\n{p.extra[-4000:]}\n" if p.extra else ""
        prompt = f"TASK: edit\nAPP: {ctx.job.name}\n{p.instruction}\n{extra}\n{file_blocks(ctx.repo_dir, shown)}"
        reply = ctx.llm.complete(SYSTEM_PROMPT, prompt)
        try:
            changed = apply_reply(ctx.repo_dir, reply, p.allowed_prefixes or None)
        except PatchError as e:
            return StepResult.failed(str(e))
        if not changed:
            return StepResult.failed("the LLM proposed no edits: " + _what_it_said(reply))
        commit_all(ctx.repo_dir, p.commit_message)
        return StepResult.ok(f"edited {', '.join(changed)}", edited=changed)


class DiffLimitParams(StrictParams):
    max_files: int = 8
    max_lines: int = 300  # added + removed


@register("step", "scm.diff_limit")
class DiffLimit(Step):
    """Blast-radius gate: a fix that rewrites half the repo is not a fix. Compares with the base branch."""

    Params = DiffLimitParams
    needs = ("scm",)

    def run(self, ctx: StepContext, p: DiffLimitParams) -> StepResult:
        base = ctx.scm.default_branch(ctx.job.name)
        rows = [r.split("\t") for r in git("diff", "--numstat", f"origin/{base}", cwd=ctx.repo_dir).splitlines()]
        lines = sum(int(a) + int(d) for a, d, _ in rows if a.isdigit() and d.isdigit())  # '-' = binary
        outputs = {"files": len(rows), "lines": lines}
        if len(rows) > p.max_files or lines > p.max_lines:
            return StepResult.failed(f"change too large: {len(rows)} files / {lines} lines "
                                     f"(limits {p.max_files} / {p.max_lines})", **outputs)
        return StepResult.ok(f"{len(rows)} file(s), {lines} line(s) changed", **outputs)
