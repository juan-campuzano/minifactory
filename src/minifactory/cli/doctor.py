"""`minifactory doctor`: what is installed, what is configured, and what a given workflow needs.

Everything that touches the machine goes through `System`, so the checks are tested with a fake one.
Secrets are never read or printed: only whether they are present. Nothing hits the network unless `--online`."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import minifactory
from minifactory import stacks, workspace
from minifactory.core.errors import FactoryError
from minifactory.core.workflow import WorkflowSpec

Status = Literal["ok", "warn", "fail", "info"]

_VERSION_ARGS = {"java": ["-version"], "javac": ["-version"]}
_AWS_EXTRA = 'install the extra: pip install "minifactory[aws]"'
_AWS_LOGIN = "run `aws configure` / `aws sso login`, or set AWS_PROFILE"
_GH_LOGIN = "run `gh auth login`"
_INSTALL_HINTS = {
    "python3": "install Python 3.11+ (https://www.python.org/downloads/)",
    "node": "install Node.js 20+ (https://nodejs.org)",
    "java": "install a JDK 17+ (java and javac)",
    "javac": "install a JDK 17+ (java and javac)",
    "flutter": "install the Flutter SDK, or FACTORY_FLUTTER=fake for offline demos only",
    "gh": f"install the GitHub CLI, then {_GH_LOGIN}",
    "git": "install git",
}


@dataclass(frozen=True)
class Check:
    group: str
    name: str
    status: Status
    detail: str = ""
    hint: str = ""


class System:
    """The machine, as the checks see it."""

    def which(self, name: str) -> str | None:
        return shutil.which(name)

    def run(self, argv: list[str], timeout: int = 10) -> tuple[int, str]:
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as e:
            return 127, str(e)
        return p.returncode, (p.stdout + p.stderr).strip()

    def getenv(self, name: str) -> str | None:
        return os.environ.get(name)

    def has_module(self, name: str) -> bool:
        return importlib.util.find_spec(name) is not None

    def aws(self) -> tuple[str | None, str | None]:
        """(how credentials are found, region): never the credentials themselves, and no network."""
        import boto3

        session = boto3.Session()
        creds = session.get_credentials()
        return (getattr(creds, "method", "found") if creds else None), session.region_name

    def completion(self) -> tuple[str | None, str | None]:
        """(your shell, 'installed' | 'stale' | 'missing'); (None, None) when the shell is not one we support."""
        from . import shell_setup

        try:
            shell = shell_setup.detect_shell()
            return shell, shell_setup.status(shell)
        except FactoryError:
            return None, None

    def aws_identity(self) -> str:  # --online only
        import boto3

        return mask_arn(boto3.client("sts").get_caller_identity()["Arn"])


_BOX = set("┌└│─╭╰┐┘╮╯├┤")


def mask_arn(arn: str) -> str:
    """Hide all but the last 4 digits of the account id: not a secret, but no need to print it whole."""
    parts = arn.split(":")
    if len(parts) > 4 and parts[4]:
        parts[4] = "*" * 8 + parts[4][-4:]
    return ":".join(parts)


def _version(system: System, tool: str) -> str:
    """The tool's own version line (skipping banners such as flutter's 'new version available' box),
    prefixed with its name when the line does not carry it (node prints just `v24.1.0`)."""
    _, out = system.run([tool, *_VERSION_ARGS.get(tool, ["--version"])])
    lines = [ln.strip() for ln in out.splitlines() if ln.strip() and not _BOX & set(ln)]
    line = next((ln for ln in lines if any(ch.isdigit() for ch in ln)), "")
    if not line:
        return "version unknown"
    line = line[:70]
    return line if tool.rstrip("3").lower() in line.lower() else f"{tool} {line}"


def _tool(system: System, group: str, tool: str, *, needed: bool, why: str = "") -> Check:
    if system.which(tool) is None:
        detail = "not installed" + (f" ({why})" if why else "")
        return Check(group, tool, "fail" if needed else "info", detail, _INSTALL_HINTS.get(tool, ""))
    return Check(group, tool, "ok", _version(system, tool))


def _profile_tools(profile: stacks.StackProfile) -> list[str]:
    return list(dict.fromkeys([*profile.requires, *profile.tools]))


def core_checks(ws: workspace.Workspace | None) -> list[Check]:
    pre = " (pre-release)" if any(ch.isalpha() for ch in minifactory.__version__) else ""
    py_ok = sys.version_info >= (3, 11)
    out = [Check("minifactory", "version", "ok", minifactory.__version__ + pre),
           Check("minifactory", "python", "ok" if py_ok else "fail", sys.version.split()[0])]
    if ws is None:
        out.append(Check("minifactory", "workspace", "warn", "none found: commands use the current folder",
                         "create one with `minifactory init`"))
        return out
    out.append(Check("minifactory", "workspace", "ok", str(ws.root) + (" (global)" if ws.is_global else "")))
    folder = ws.root / ws.config.workflows_dir
    out.append(Check("minifactory", "workflows folder", "ok" if folder.is_dir() else "warn", str(folder),
                     "" if folder.is_dir() else "create it, or `minifactory workflows copy NAME`"))
    return out


def completion_check(system: System) -> list[Check]:
    shell, state = system.completion()
    if shell is None:
        return []
    detail, status = {"installed": (f"installed for {shell}", "ok"),
                      "stale": (f"installed for {shell}, but out of date", "warn"),
                      "missing": (f"not installed for {shell}", "info")}[str(state)]
    return [Check("minifactory", "tab completion", status, detail,
                  "" if state == "installed" else "run `minifactory completion install`")]


def toolchain_checks(system: System, root: Path | None) -> list[Check]:
    """One line per stack profile. A missing toolchain is information, not a failure: it only matters
    if you use that stack (`doctor WORKFLOW` is the strict version)."""
    out = []
    for name, profile in stacks.available(root).items():
        tools = _profile_tools(profile)
        missing = [t for t in tools if system.which(t) is None]
        if missing:
            out.append(Check("stacks", name, "info", f"{', '.join(missing)} not installed",
                             _INSTALL_HINTS.get(missing[0], "")))
        else:
            detail = "; ".join(_version(system, t) for t in tools) or "no tools needed"
            out.append(Check("stacks", name, "ok", detail))
    return out


def _bedrock_checks(system: System, online: bool) -> list[Check]:
    if not system.has_module("boto3"):
        return [Check("llm", "bedrock", "info", "boto3 is not installed", _AWS_EXTRA)]
    try:
        method, region = system.aws()
    except Exception as e:  # noqa: BLE001 - a broken AWS config is a finding, not a crash
        return [Check("llm", "bedrock", "warn", f"AWS configuration error: {type(e).__name__}")]
    if method is None:
        return [Check("llm", "bedrock", "info", "boto3 installed, no AWS credentials found", _AWS_LOGIN)]
    out = [Check("llm", "bedrock", "ok", f"credentials via {method}; region {region or 'not set'}",
                 "" if region else "set a region (AWS_REGION) or the workflow's `region:`")]
    if online:
        try:
            out.append(Check("llm", "aws identity", "ok", system.aws_identity()))
        except Exception as e:  # noqa: BLE001
            out.append(Check("llm", "aws identity", "fail", f"{type(e).__name__}: the credentials do not work"))
    return out


def _gh_auth(system: System, group: str) -> Check:
    code, _ = system.run(["gh", "auth", "status"], 15)
    return Check(group, "gh auth", "ok" if code == 0 else "fail",
                 "logged in" if code == 0 else "not logged in", "" if code == 0 else _GH_LOGIN)


def service_checks(system: System, online: bool) -> list[Check]:
    out = _bedrock_checks(system, online)
    key = bool(system.getenv("TYPESAFE_API_KEY"))
    out.append(Check("router", "TYPESAFE_API_KEY", "ok" if key else "info",
                     "set" if key else "not set (use `--router keyword`, or set it)"))
    out.append(_tool(system, "scm", "git", needed=False))
    gh = _tool(system, "scm", "gh", needed=False)
    out.append(gh)
    if gh.status == "ok" and online:
        out.append(_gh_auth(system, "scm"))
    return out


def agent_tool_checks(system: System) -> list[Check]:
    """Optional agent CLIs and isolation tools. Informational: minifactory does not use them yet."""
    out = []
    for group, tools in (("agent CLIs (not used yet)", ("claude", "copilot", "gemini", "codex")),
                         ("isolation (not used yet)", ("srt", "bwrap", "sandbox-exec", "docker", "podman"))):
        for tool in tools:
            found = system.which(tool)
            shown = _version(system, tool) if group.startswith("agent") else "available"
            out.append(Check(group, tool, "ok" if found else "info", shown if found else "not installed"))
    return out


def _llm_needs(system: System, spec: WorkflowSpec, group: str) -> list[Check]:
    refs = [r for r in (spec.providers.get("llm"), *spec.llms.values()) if r is not None]
    out: list[Check] = []
    if any(r.use == "bedrock" for r in refs):
        if not system.has_module("boto3"):
            out.append(Check(group, "boto3", "fail", "not installed", _AWS_EXTRA))
        else:
            method, _ = system.aws()
            out.append(Check(group, "AWS credentials", "ok" if method else "fail",
                             f"via {method}" if method else "not found", "" if method else _AWS_LOGIN))
    seen_secrets: set[str] = set()
    for llm in refs:
        if llm.use == "openai":
            secret = str(llm.with_.get("api_key_secret", "LLM_API_KEY"))
            if secret in seen_secrets:
                continue
            seen_secrets.add(secret)
            present = bool(system.getenv(secret))
            out.append(Check(group, secret, "ok" if present else "fail", "set" if present else "not set",
                             "" if present else f"export {secret}=..."))
    return out


def _stack_needs(system: System, spec: WorkflowSpec, group: str) -> list[Check]:
    uses_stacks = {"agent.plan_app", "agent.implement_spec"}
    steps = [s for s in spec.steps if s.use.startswith("stack.") or s.use in uses_stacks]
    if not steps:
        return []
    named = {s.with_["stack"] for s in steps
             if isinstance(s.with_.get("stack"), str) and not s.with_["stack"].startswith("${")}
    profiles = {n: p for n, p in stacks.available().items() if not named or n in named}
    out = []
    for name, profile in profiles.items():
        gone = [t for t in _profile_tools(profile) if system.which(t) is None]
        status: Status = "ok" if not gone else ("fail" if named else "info")  # a fixed stack must work
        out.append(Check(group, f"stack {name}", status, "toolchain ready" if not gone else
                         f"{', '.join(gone)} not installed", "" if not gone else _INSTALL_HINTS.get(gone[0], "")))
    return out


def workflow_checks(system: System, spec: WorkflowSpec, online: bool) -> list[Check]:
    """What THIS workflow needs, derived from its providers and steps; a missing one is a failure."""
    group = f"needs of '{spec.name}'"
    out = _llm_needs(system, spec, group)
    scm = spec.providers.get("scm")
    if scm and scm.use == "github":
        out.append(_tool(system, group, "gh", needed=True, why="the github provider uses it"))
        if online and system.which("gh"):
            out.append(_gh_auth(system, group))
    if scm:
        out.append(_tool(system, group, "git", needed=True, why="the scm providers use it"))
    flutter = [s for s in spec.steps if s.use.startswith("flutter.") and s.with_.get("tool") != "fake"]
    if flutter:
        out.append(_tool(system, group, "flutter", needed=True, why=f"step '{flutter[0].id}'"))
    return out + _stack_needs(system, spec, group)


def run_checks(system: System, ws: workspace.Workspace | None, *, workflow: WorkflowSpec | None = None,
               online: bool = False) -> list[Check]:
    checks = core_checks(ws)
    if workflow is not None:
        return checks + workflow_checks(system, workflow, online)
    root = ws.root if ws else None
    return (checks + completion_check(system) + toolchain_checks(system, root)
            + service_checks(system, online) + agent_tool_checks(system))


def exit_code(checks: list[Check]) -> int:
    return 1 if any(c.status == "fail" for c in checks) else 0


def as_json(checks: list[Check]) -> list[dict[str, Any]]:
    return [asdict(c) for c in checks]


_MARK = {"ok": ("✓", "green"), "warn": ("!", "yellow"), "fail": ("✗", "bold red"), "info": ("·", "dim")}


def render(checks: list[Check], console: Any) -> None:
    from rich.table import Table
    from rich.text import Text

    group = None
    for c in checks:
        if c.group != group:
            group = c.group
            console.print(Text(f"\n{group}", style="bold"))
        mark, style = _MARK[c.status]
        line = Text.assemble((f"  {mark} ", style), (f"{c.name:<20}", "default"),
                             (c.detail, "dim" if c.status == "info" else "default"))
        if c.hint and c.status != "ok":
            line.append(f"  → {c.hint}", style="cyan")
        console.print(line)
    n = {s: sum(c.status == s for c in checks) for s in _MARK}
    summary = Table.grid(padding=(0, 2))
    summary.add_row(Text(f"{n['ok']} ok", style="green"), Text(f"{n['warn']} warnings", style="yellow"),
                    Text(f"{n['fail']} failing", style="red" if n["fail"] else "dim"),
                    Text(f"{n['info']} not installed / not set", style="dim"))
    console.print()
    console.print(summary)
