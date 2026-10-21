"""Stack profiles: language-specific knowledge as data. The end-to-end tests run the REAL toolchains
(python3, node, javac) with a scripted LLM, and are skipped when a tool is not installed."""

import json
import shutil

import pytest
import yaml

from minifactory import stacks, templates, workspace
from minifactory.core import registry
from minifactory.core.engine import Engine
from minifactory.core.models import Job
from minifactory.core.workflow import WorkflowSpec, validate_spec
from minifactory.plugins.builtin.intakes import AppSpecIntake
from minifactory.plugins.builtin.util import collect_files, glob_match

registry.load_plugins()

NEEDS = {"python": ["python3"], "node": ["node"], "java": ["javac", "java"]}


def has(stack):
    return all(shutil.which(t) for t in NEEDS[stack])


# -- what the scripted LLM writes for each stack ------------------------------------------------
FILES = {
    "python": {
        "src/hello_cli/__init__.py": '"""Hello CLI."""',
        "src/hello_cli/cli.py": (
            "import argparse\n\n\ndef greet(name=None):\n    return f\"Hello, {name or 'World'}!\"\n\n\n"
            "def main(argv=None):\n    parser = argparse.ArgumentParser()\n    parser.add_argument('name', nargs='?')\n"
            "    print(greet(parser.parse_args(argv).name))\n    return 0\n"),
        "tests/test_cli.py": (
            "import unittest\n\nfrom hello_cli.cli import greet\n\n\nclass GreetTest(unittest.TestCase):\n"
            "    def test_default(self):\n        self.assertEqual(greet(), 'Hello, World!')\n\n"
            "    def test_name(self):\n        self.assertEqual(greet('Ada'), 'Hello, Ada!')\n"),
    },
    "node": {
        "src/cli.js": ("function greet(name) { return `Hello, ${name || 'World'}!`; }\n"
                       "module.exports = { greet };\n"),
        "test/cli.test.js": ("const test = require('node:test');\nconst assert = require('node:assert');\n"
                             "const { greet } = require('../src/cli.js');\n\n"
                             "test('default', () => assert.strictEqual(greet(), 'Hello, World!'));\n"
                             "test('name', () => assert.strictEqual(greet('Ada'), 'Hello, Ada!'));\n"),
    },
    "java": {
        "src/main/java/Greeter.java": (
            "public class Greeter {\n    public static String greet(String name) {\n"
            "        return \"Hello, \" + (name == null ? \"World\" : name) + \"!\";\n    }\n}\n"),
        "src/test/java/GreeterTest.java": (
            "public class GreeterTest {\n    public static void main(String[] args) {\n"
            "        assert Greeter.greet(null).equals(\"Hello, World!\");\n"
            "        assert Greeter.greet(\"Ada\").equals(\"Hello, Ada!\");\n    }\n}\n"),
    },
}
PLAN = {s: {"features": [{"id": "greeter", "title": "Greeter", "files": list(f)}]} for s, f in FILES.items()}


def blocks(stack, **override):
    files = {**FILES[stack], **override}
    return "\n".join(f"FILE: {p}\n{c.rstrip()}\nEND_FILE" for p, c in files.items())


class StackLLM:
    """Replies by TASK and STACK. `broken` makes the first implementation wrong and the repair right."""

    seen: list[str] = []
    broken = False

    def complete(self, system, prompt):
        StackLLM.seen.append(prompt)
        stack = next((s for s in FILES if f"STACK: {s}" in prompt), "python")
        if "TASK: plan_app" in prompt:
            return json.dumps(PLAN[stack])
        if "TASK: repair" in prompt:
            return blocks(stack)
        if StackLLM.broken:
            return blocks("python", **{"src/hello_cli/cli.py": "def greet(:\n    pass"})
        return blocks(stack)


registry.register("llm", "t.stack")(type("StackLLMProvider", (StackLLM,), {"__init__": lambda self: None}))


@pytest.fixture()
def factory_ws(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    root = tmp_path / "ws"
    workspace.init(root)
    templates.copy("app-factory", root)
    monkeypatch.chdir(root)
    StackLLM.seen, StackLLM.broken = [], False
    return root


def run_app_factory(root, stack, name="hello_cli"):
    data = yaml.safe_load((root / "workflows" / "app-factory.yaml").read_text())
    data["providers"]["llm"] = {"use": "t.stack"}
    data["providers"]["scm"] = {"use": "local-dir", "with": {"dir": str(root / "out")}}
    spec = WorkflowSpec.model_validate(data)
    validate_spec(spec)
    job = Job(id=name, name=name, attrs={"description": "A tiny greeting program.", "features": [], "size": "minimal",
                                         "stack": stack})
    return Engine(spec, root / ".minifactory" / "runs").run_job(job)


# -- profiles ----------------------------------------------------------------------------------
def test_the_packaged_profiles_are_valid_and_complete():
    profiles = stacks.available()
    assert {"python", "node", "java", "flutter"} <= set(profiles)
    for p in profiles.values():
        assert {"analyze", "test", "test_files"} <= set(p.commands), p.name
        assert p.test_prefixes and p.repro_test_path.startswith(tuple(p.test_prefixes)), p.name
        assert p.hints.strip() and p.file_example, p.name


def test_a_workspace_profile_adds_a_stack_and_overrides_a_packaged_one(tmp_path):
    folder = tmp_path / "stacks"
    folder.mkdir()
    base = yaml.safe_load((stacks.PROFILES_DIR / "python.yaml").read_text())
    (folder / "ruby.yaml").write_text(yaml.safe_dump({**base, "name": "ruby", "detect": ["Gemfile"]}))
    (folder / "python.yaml").write_text(yaml.safe_dump({**base, "description": "my python"}))
    found = stacks.available(tmp_path)
    assert "ruby" in found and found["python"].description == "my python"
    assert stacks.detect(tmp_path, tmp_path) == []
    (tmp_path / "Gemfile").write_text("")
    assert stacks.detect(tmp_path, tmp_path) == ["ruby"]


def test_a_broken_profile_is_a_clear_error(tmp_path):
    (tmp_path / "stacks").mkdir()
    (tmp_path / "stacks" / "bad.yaml").write_text("name: bad\nunknown_key: 1\n")
    with pytest.raises(stacks.StackError, match="bad.yaml"):
        stacks.available(tmp_path)
    with pytest.raises(stacks.StackError, match="Available"):
        stacks.get("cobol", tmp_path / "elsewhere")


def test_detect_recognises_repositories_and_reports_ambiguity(tmp_path):
    assert stacks.detect(tmp_path) == []
    (tmp_path / "pyproject.toml").write_text("")
    assert stacks.detect(tmp_path) == ["python"]
    (tmp_path / "package.json").write_text("{}")
    assert sorted(stacks.detect(tmp_path)) == ["node", "python"]


def test_project_names_are_valid_in_every_stack():
    assert stacks.project_name("Hello World-CLI") == "hello_world_cli"
    assert stacks.project_name("acme/todo_app") == "acme_todo_app"
    assert stacks.project_name("2fast").startswith("app_")


def test_placeholders_are_replaced_without_str_format_so_shell_braces_survive():
    out = stacks.render("echo ${f#src/} {name} {pkg} {paths}", name="a_b", paths=["x y.py"])
    assert out == "echo ${f#src/} a_b ab 'x y.py'"


def test_glob_match_spans_folders_only_with_double_star():
    assert glob_match("src/a.py", "src/**/*.py") and glob_match("src/x/y/a.py", "src/**/*.py")
    assert glob_match("a.py", "*.py") and not glob_match("x/a.py", "*.py")
    assert glob_match("pyproject.toml", "pyproject.toml") and not glob_match("pyproject.tomls", "pyproject.toml")


def test_context_collection_skips_dependency_and_build_folders(tmp_path):
    for rel in ("src/a.js", "node_modules/pkg/index.js", ".git/hooks/x.js", "build/out.js"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x")
    assert collect_files(tmp_path, [], ["**/*.js"]) == ["src/a.js"]


# -- the intake picks a stack, or says it cannot --------------------------------------------------
class ReplyLLM:
    def __init__(self, reply):
        self.reply, self.system = reply, ""

    def complete(self, system, prompt):
        self.system = system
        return self.reply


def spec_reply(stack):
    return json.dumps({"name": "hello_cli", "description": "Says hello to a user.", "features": [], "stack": stack})


def test_the_intake_prompt_lists_the_installed_stacks_and_validates_the_choice():
    llm = ReplyLLM(spec_reply("python"))
    job = AppSpecIntake().build("a python cli that says hello", llm)
    assert job.attrs["stack"] == "python"
    assert all(f"- {name}:" in llm.system for name in ("python", "node", "java", "flutter"))


@pytest.mark.parametrize("stack", ["unsupported", "cobol", None])
def test_an_unsupported_or_missing_stack_is_refused_with_the_alternatives(stack):
    with pytest.raises(ValueError, match="no supported stack.*python"):
        AppSpecIntake().build("a cobol program", ReplyLLM(spec_reply(stack)))


# -- the planner follows the stack, not a hardcoded language ----------------------------------------
def planned(stack, factory_ws=None):
    from minifactory.core.context import StepContext
    from minifactory.plugins.builtin.steps_agent import PlanApp

    llm = StackLLM()
    attrs = {"description": "d", "size": "minimal", **({"stack": stack} if stack else {})}
    ctx = StepContext(job=Job(id="a", name="hello_cli", attrs=attrs), work_dir=None, scm=None, llm=llm,
                      secrets=None, emit=lambda *a, **k: None)
    StackLLM.seen = []
    PlanApp().run(ctx, PlanApp.Params())
    return StackLLM.seen[0]


def test_plan_prompts_use_each_stacks_example_and_never_the_old_dart_one():
    py, node, java = planned("python"), planned("node"), planned("java")
    assert "src/hello_cli/cli.py" in py and "STACK: python" in py and ".dart" not in py
    assert "src/cli.js" in node and "node:test" in node
    assert "Greeter.java" in java and "JDK only" in java
    neutral = planned(None)
    assert "path/to/source_file" in neutral and ".dart" not in neutral and "STACK:" not in neutral
    assert "lib/todo.dart" in planned("flutter")  # Flutter still gets its own example


# -- end to end, with the real toolchains -----------------------------------------------------------
@pytest.mark.parametrize("stack", ["python", "node", "java"])
def test_a_project_is_scaffolded_built_tested_and_delivered(stack, factory_ws):
    if not has(stack):
        pytest.skip(f"{stack} toolchain not installed")
    result = run_app_factory(factory_ws, stack)
    assert result.outcome == "succeeded", result.reason
    status = {s.id: s.status for s in result.steps}
    assert status["analyze"] == "ok" and status["test"] == "ok" and status["repair"] == "skipped"
    delivered = factory_ws / "out" / "hello_cli"
    for rel in FILES[stack]:
        assert (delivered / rel).is_file(), rel
    assert (delivered / ".git").is_dir()


def test_the_scaffold_seeds_each_stacks_manifest(factory_ws):
    if not has("node"):
        pytest.skip("node not installed")
    run_app_factory(factory_ws, "node")
    manifest = json.loads((factory_ws / "out" / "hello_cli" / "package.json").read_text())
    assert manifest["name"] == "hello_cli" and manifest["scripts"]["test"] == "node --test"


@pytest.mark.skipif(not has("python"), reason="python3 not installed")
def test_a_broken_first_draft_goes_through_the_repair_loop_using_the_stacks_own_checks(factory_ws):
    StackLLM.broken = True
    result = run_app_factory(factory_ws, "python")
    status = {s.id: s.status for s in result.steps}
    assert status["analyze"] == "failed" and status["repair"] == "ok"
    assert result.outcome == "succeeded", result.reason
    repairs = [p for p in StackLLM.seen if "TASK: repair" in p]
    assert repairs and all("STACK: python" in p and "STANDARD LIBRARY ONLY" in p for p in repairs)


def test_a_missing_toolchain_fails_early_with_a_clear_message(factory_ws, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    result = run_app_factory(factory_ws, "python")
    assert result.outcome == "failed" and "needs python3 on PATH" in result.reason


# -- fixing a bug in an existing repository, stack detected from its files ------------------------------
def patch(path, search, replace):
    return f"PATCH: {path}\n<<<<<<< SEARCH\n{search}\n=======\n{replace}\n>>>>>>> REPLACE\nEND_PATCH"


class BugLLM:
    def complete(self, system, prompt):
        if "TASK: locate" in prompt:
            return json.dumps({"files": ["src/calc.py"]})
        if "REPRO_TEST_PATH: tests/test_factory_repro.py" in prompt:
            return ("FILE: tests/test_factory_repro.py\nimport unittest\nfrom calc import add\n\n\n"
                    "class T(unittest.TestCase):\n    def test_add(self):\n"
                    "        self.assertEqual(add(2, 3), 5)\nEND_FILE")
        return patch("src/calc.py", "    return a - b", "    return a + b")


registry.register("llm", "t.pybug")(type("PyBugLLM", (BugLLM,), {"__init__": lambda self: None}))


def make_python_remote(tmp_path):
    from minifactory.plugins.builtin.util import git

    seed = tmp_path / "seed"
    (seed / "src").mkdir(parents=True)
    (seed / "tests").mkdir()
    (seed / "pyproject.toml").write_text("[project]\nname='calc'\nversion='0.1.0'\n")
    (seed / "src" / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    (seed / "tests" / "test_ok.py").write_text("import unittest\n\n\nclass T(unittest.TestCase):\n"
                                               "    def test_ok(self):\n        self.assertTrue(True)\n")
    git("init", "--quiet", "-b", "main", cwd=seed)
    git("add", "-A", cwd=seed)
    git("-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "initial", cwd=seed)
    remote = tmp_path / "remotes" / "acme" / "calc.git"
    remote.parent.mkdir(parents=True)
    git("clone", "--quiet", "--bare", str(seed), str(remote))
    return remote


@pytest.mark.skipif(not has("python"), reason="python3 not installed")
def test_fix_bug_detects_the_stack_reproduces_the_bug_and_fixes_it(tmp_path, monkeypatch):
    from minifactory.plugins.builtin.intakes import repo_task_job
    from minifactory.plugins.builtin.util import git

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    root = tmp_path / "ws"
    workspace.init(root)
    templates.copy("fix-bug", root)
    monkeypatch.chdir(root)
    remote = make_python_remote(tmp_path)
    data = yaml.safe_load((root / "workflows" / "fix-bug.yaml").read_text())
    data["providers"] = {"scm": {"use": "local-git", "with": {"remotes_dir": str(tmp_path / "remotes"),
                                                             "prs_dir": str(tmp_path / "prs")}},
                         "llm": {"use": "t.pybug"}}
    spec = WorkflowSpec.model_validate(data)
    validate_spec(spec)
    job = repo_task_job("acme/calc", "add(2, 3) returns -1 instead of 5")
    result = Engine(spec, root / ".minifactory" / "runs").run_job(job)
    status = {s.id: s.status for s in result.steps}
    assert result.outcome == "succeeded", result.reason
    assert next(s for s in result.steps if s.id == "detect").outputs["stack"] == "python"
    assert status["repro_fails"] == "ok" and status["test"] == "ok" and status["repair"] == "skipped"
    branch = next(json.loads(p.read_text())["branch"] for p in (tmp_path / "prs" / "acme" / "calc").glob("*.json"))
    changed = git("--git-dir", str(remote), "diff", "--name-only", f"main..{branch}").split()
    assert sorted(changed) == ["src/calc.py", "tests/test_factory_repro.py"], changed  # no .pyc in the pull request
    assert "a + b" in git("--git-dir", str(remote), "show", f"{branch}:src/calc.py")
    assert "a - b" in git("--git-dir", str(remote), "show", "main:src/calc.py")  # the default branch is untouched


def test_an_unrecognised_repository_stops_before_anything_is_spent(tmp_path, monkeypatch):
    from minifactory.core.context import StepContext
    from minifactory.plugins.builtin.steps_stack import Detect

    ctx = StepContext(job=Job(id="j", name="j"), work_dir=tmp_path, scm=None, llm=None, secrets=None,
                      emit=lambda *a, **k: None)
    ctx.repo_dir.mkdir()
    (ctx.repo_dir / "main.cob").write_text("")
    monkeypatch.chdir(tmp_path)
    result = Detect().run(ctx, Detect.Params())
    assert result.status == "failed" and "unsupported stack" in result.message
    assert "stacks/<name>.yaml" in result.message


@pytest.mark.skipif(not has("python"), reason="python3 not installed")
def test_the_python_analyze_check_finds_syntax_errors_and_leaves_no_bytecode(tmp_path):
    from minifactory.core.context import StepContext
    from minifactory.plugins.builtin.steps_stack import Check

    ctx = StepContext(job=Job(id="j", name="j", attrs={"stack": "python"}), work_dir=tmp_path, scm=None, llm=None,
                      secrets=None, emit=lambda *a, **k: None)
    (ctx.repo_dir / "src").mkdir(parents=True)
    (ctx.repo_dir / "src" / "ok.py").write_text("x = 1\n")
    assert Check().run(ctx, Check.Params(check="analyze")).status == "ok"
    (ctx.repo_dir / "src" / "bad.py").write_text("def broken(:\n")
    result = Check().run(ctx, Check.Params(check="analyze"))
    assert result.status == "failed" and "SyntaxError" in result.message
    assert not list(ctx.repo_dir.rglob("*.pyc")) and not list(ctx.repo_dir.rglob("__pycache__"))


def test_layout_rules_reach_new_projects_but_never_existing_repositories():
    python = stacks.get("python")
    existing = stacks.guidance(python, "textkit", new_project=False)
    fresh = stacks.guidance(python, "hello_cli", new_project=True)
    assert "unittest" in existing and "STANDARD LIBRARY ONLY" not in existing and "src/hello_cli" not in existing
    assert "STANDARD LIBRARY ONLY" in fresh and "src/hello_cli/" in fresh
    for profile in stacks.available().values():  # every stack tells existing-repo agents how its tests are written
        assert profile.hints.strip(), profile.name
