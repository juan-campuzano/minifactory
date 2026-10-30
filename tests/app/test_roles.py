"""Roles: packaged and workspace role profiles (`roles/*.yaml`), prompt persona + default skills,
file-path boundaries (`allowed_prefixes`, `forbid_prefixes`, `tests_only`), and per-role LLMs (`llms:`)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from minifactory import catalog, review, roles
from minifactory.cli import doctor
from minifactory.core import registry
from minifactory.core.context import StepContext
from minifactory.core.engine import Engine
from minifactory.core.errors import WorkflowError
from minifactory.core.models import Job
from minifactory.core.workflow import load_workflow
from minifactory.plugins.builtin.steps.existing import Edit
from minifactory.plugins.builtin.support.git import git


class RecordingLLM:
    def __init__(self, reply: str):
        self.reply = reply
        self.prompts: list[str] = []

    def complete(self, system: str, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.reply


def _ctx(tmp_path: Path, reply: str, *, stack: str | None = None, llms: dict | None = None,
         events: list | None = None) -> tuple[StepContext, RecordingLLM]:
    registry.load_plugins()
    llm = RecordingLLM(reply)
    rec = events if events is not None else []
    attrs = {"stack": stack} if stack else {}
    ctx = StepContext(
        job=Job(id="j", name="demo_app", attrs=attrs),
        work_dir=tmp_path,
        scm=None,
        llm=llm,
        secrets=None,
        emit=lambda *a, **k: rec.append((a, k)),
        llms=llms or {},
    )
    ctx.repo_dir.mkdir(parents=True, exist_ok=True)
    git("init", "-q", cwd=ctx.repo_dir)
    return ctx, llm


def test_packaged_roles_ship_and_workspace_roles_override_by_name(tmp_path: Path):
    packaged = roles.available(tmp_path)
    assert {"architect", "designer", "developer", "qa", "reviewer"} <= set(packaged)
    assert "test/" in packaged["designer"].forbid_prefixes
    assert packaged["qa"].tests_only is True

    (tmp_path / "roles").mkdir()
    (tmp_path / "roles/designer.yaml").write_text(
        "name: designer\ndescription: Custom brand designer\npersona: Follow brand guidelines.\n"
        "allowed_prefixes: [DESIGN.md, ui/]\n"
    )
    overridden = roles.get("designer", tmp_path)
    assert overridden.description == "Custom brand designer"
    assert overridden.allowed_prefixes == ["DESIGN.md", "ui/"]


def test_unknown_or_malformed_roles_fail_clearly(tmp_path: Path):
    with pytest.raises(roles.RoleError, match="unknown role 'wizard'"):
        roles.get("wizard", tmp_path)
    with pytest.raises(roles.RoleError, match="no role given"):
        roles.get("", tmp_path)

    (tmp_path / "roles").mkdir()
    (tmp_path / "roles/bad.yaml").write_text("name: Bad Name\ndescription: x\npersona: y\n")
    with pytest.raises(roles.RoleError, match="cannot load role profile"):
        roles.available(tmp_path)


def test_designer_role_injects_persona_allows_design_files_and_forbids_tests(tmp_path: Path):
    events: list = []
    ctx, llm = _ctx(tmp_path / "ok", "FILE: DESIGN.md\n# Tokens\nEND_FILE", events=events)
    res = Edit().run(ctx, Edit.Params(instruction="define tokens", role="designer"))
    assert res.status == "ok"
    assert (ctx.repo_dir / "DESIGN.md").read_text() == "# Tokens\n"
    assert "ROLE: designer" in llm.prompts[0] and "Product Designer" in llm.prompts[0]
    assert any(a[0] == "role_used" and k.get("role") == "designer" for a, k in events)

    ctx_bad, _ = _ctx(tmp_path / "bad", "FILE: tests/test_ui.py\nassert True\nEND_FILE")
    bad_res = Edit().run(ctx_bad, Edit.Params(instruction="touch tests", role="designer"))
    assert bad_res.status == "failed"
    assert "forbidden path" in bad_res.message
    assert not (ctx_bad.repo_dir / "tests/test_ui.py").exists()


def test_qa_role_enforces_tests_only_from_the_stack_profile(tmp_path: Path):
    ctx_ok, llm = _ctx(tmp_path / "ok", "FILE: tests/test_edge.py\nassert 1 == 1\nEND_FILE", stack="python")
    res = Edit().run(ctx_ok, Edit.Params(instruction="add edge test", role="qa"))
    assert res.status == "ok" and "ROLE: qa" in llm.prompts[0]
    assert (ctx_ok.repo_dir / "tests/test_edge.py").is_file()

    ctx_bad, _ = _ctx(tmp_path / "bad", "FILE: src/demo_app/main.py\nx = 1\nEND_FILE", stack="python")
    bad_res = Edit().run(ctx_bad, Edit.Params(instruction="touch prod code", role="qa"))
    assert bad_res.status == "failed"
    assert "outside the allowed paths" in bad_res.message
    assert not (ctx_bad.repo_dir / "src/demo_app/main.py").exists()


def test_role_merges_default_skills_with_step_skills(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "home/.config"))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "minifactory.yaml").write_text("schema_version: 1\n")
    for s in ("ui-kit", "a11y"):
        folder = tmp_path / ".minifactory/skills" / s
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(f"---\nname: {s}\ndescription: {s} guide\n---\nUse {s}.\n")
    (tmp_path / "roles").mkdir()
    (tmp_path / "roles/designer.yaml").write_text(
        "name: designer\ndescription: UI designer\npersona: Design first.\nskills: [ui-kit]\n"
    )
    ctx, llm = _ctx(tmp_path / "run", "FILE: DESIGN.md\nok\nEND_FILE")
    res = Edit().run(ctx, Edit.Params(instruction="draft design", role="designer", skills=["a11y"]))
    assert res.status == "ok"
    assert "### ui-kit\nUse ui-kit." in llm.prompts[0]
    assert "### a11y\nUse a11y." in llm.prompts[0]


def test_workflow_runs_designer_and_developer_roles_with_dedicated_llms(tmp_path: Path,
                                                                        monkeypatch: pytest.MonkeyPatch):
    registry.load_plugins()
    monkeypatch.chdir(tmp_path)
    wf_path = tmp_path / "workflow.yaml"
    wf_path.write_text(
        """
schema_version: 1
name: role-demo
source:
  use: static
  with:
    jobs:
      - id: app1
        name: app1
        stack: python
providers:
  llm:
    use: scripted
    with:
      replies:
        - |
          FILE: src/app1/__init__.py
          THEME = "solarized"
          END_FILE
llms:
  designer:
    use: scripted
    with:
      replies:
        - |
          FILE: DESIGN.md
          Palette: solarized
          END_FILE
steps:
  - id: init
    use: workdir.init
  - id: design
    use: agent.edit
    with:
      role: designer
      instruction: "Create DESIGN.md with the colour palette"
  - id: implement
    use: agent.edit
    with:
      role: developer
      files: [DESIGN.md]
      instruction: "Implement the module using DESIGN.md"
"""
    )
    spec = load_workflow(wf_path)
    runs_dir = tmp_path / "runs"
    engine = Engine(spec, runs_dir=runs_dir)
    job = engine.source.jobs()[0]
    result = engine.run_job(job)
    assert result.outcome == "succeeded"

    repo = runs_dir / "role-demo/app1/work/repo"
    assert (repo / "DESIGN.md").read_text().strip() == "Palette: solarized"
    assert 'THEME = "solarized"' in (repo / "src/app1/__init__.py").read_text()

    events = [json.loads(line) for line in (runs_dir / "role-demo/events.jsonl").read_text().splitlines()]
    llm_calls = [e for e in events if e["type"] == "llm_call"]
    assert len(llm_calls) == 2
    assert llm_calls[0].get("role") == "designer"
    assert "role" not in llm_calls[1]
    role_events = [e for e in events if e["type"] == "role_used"]
    assert [(e["role"], e["llm"]) for e in role_events] == [("designer", "custom"), ("developer", "default")]


def test_workflow_validation_and_review_and_doctor_understand_role_llms(tmp_path: Path):
    registry.load_plugins()
    wf = tmp_path / "wf.yaml"
    wf.write_text(
        """
schema_version: 1
name: role-only-llm
source: {use: static, with: {jobs: []}}
llms:
  designer: {use: bedrock, with: {model_id: m}}
steps:
  - id: design
    use: agent.edit
    with: {role: designer, instruction: "design it"}
"""
    )
    spec = load_workflow(wf)
    findings = [str(f) for f in review.review(spec)]
    assert any("llm for role 'designer': bedrock" in f for f in findings)

    class FakeSystem(doctor.System):
        def has_module(self, name: str) -> bool:
            return False

    checks = doctor.workflow_checks(FakeSystem(), spec, online=False)
    assert any(c.name == "boto3" and c.status == "fail" for c in checks)
    assert "# Roles installed" in catalog.render_markdown()

    wf_missing = tmp_path / "missing.yaml"
    wf_missing.write_text(
        """
schema_version: 1
name: missing-llm
source: {use: static, with: {jobs: []}}
llms:
  designer: {use: fixture, with: {path: x}}
steps:
  - id: dev
    use: agent.edit
    with: {role: developer, instruction: "no default llm and no developer llm"}
"""
    )
    with pytest.raises(WorkflowError, match="needs the 'llm' provider"):
        load_workflow(wf_missing)
