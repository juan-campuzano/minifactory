"""The structure of the project, enforced. If one of these fails, the answer is usually to move the code
to the right layer, not to edit the test; AGENTS.md ("Where does new code go") explains each rule.

    core/                    the engine and the ports. Imports nothing else of minifactory.
    plugins/builtin/
      support/               helpers shared by plugins (git, shell, edits, text, tls). Not plugins.
      steps/  providers/  routing/     plugins, one folder per kind of thing they are
      tools/                 programs run as subprocesses: standard library only
    stacks, templates, catalog, review, workspace, ask      domain services (one concern each)
    cli/                     the command line and everything that prints
"""

import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]
SRC = ROOT / "src" / "minifactory"
TESTS = ROOT / "tests"

DOMAIN = {"stacks", "templates", "catalog", "review", "workspace", "ask"}
TOP_LEVEL_MODULES = {"__init__", "__main__", *DOMAIN}
TOP_LEVEL_PACKAGES = {"cli", "core", "plugins", "profiles", "templates"}
MAX_LINES = 450  # a module that grows past this wants splitting, not more lines


def module_of(path: Path) -> str:
    parts = list(path.relative_to(SRC.parent).with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def imports_of(path: Path) -> set[str]:
    """Absolute dotted names of everything this file imports from minifactory (relative ones resolved)."""
    tree = ast.parse(path.read_text())
    package = module_of(path).rsplit(".", 1)[0] if path.name != "__init__.py" else module_of(path)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names if a.name.split(".")[0] == "minifactory"}
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = ".".join(package.split(".")[: len(package.split(".")) - node.level + 1])
                module = f"{base}.{node.module}" if node.module else base
            else:
                module = node.module or ""
            if module.split(".")[0] == "minifactory":
                found.add(module)
                found |= {f"{module}.{a.name}" for a in node.names}
    return found


def python_files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*.py") if "__pycache__" not in p.parts)


def violations(folder: Path, allowed_prefixes: tuple[str, ...]) -> list[str]:
    bad = []
    for path in python_files(folder):
        for name in imports_of(path):
            ok = name == "minifactory" or name.startswith((*allowed_prefixes, "minifactory.core"))
            if not ok:
                bad.append(f"{path.relative_to(ROOT)} imports {name}")
    return bad


def test_the_core_imports_nothing_but_itself():
    assert violations(SRC / "core", ("minifactory.core",)) == []


def test_support_helpers_depend_only_on_each_other_and_the_core():
    assert violations(SRC / "plugins/builtin/support", ("minifactory.plugins.builtin.support",)) == []


def test_tools_run_as_subprocesses_so_they_use_only_the_standard_library():
    for path in python_files(SRC / "plugins/builtin/tools"):
        assert not imports_of(path), f"{path.name} imports {imports_of(path)}"


def test_plugins_never_reach_up_into_the_command_line_or_the_ask_flow():
    banned = ("minifactory.cli", "minifactory.ask", "minifactory.workspace")
    bad = [f"{p.relative_to(ROOT)} imports {n}" for p in python_files(SRC / "plugins")
           for n in imports_of(p) if n.startswith(banned)]
    assert bad == []


def test_each_kind_of_plugin_only_uses_its_own_kind_and_the_shared_support():
    def allowed(kind: str, extra: tuple[str, ...] = ()) -> tuple[str, ...]:
        return (f"minifactory.plugins.builtin.{kind}", "minifactory.plugins.builtin.support",
                *(f"minifactory.{d}" for d in DOMAIN), *extra)

    problems = []
    secrets = ("minifactory.plugins.builtin.providers.secrets",)
    for kind, extra in {"steps": (), "providers": (), "routing": secrets}.items():
        problems += violations(SRC / "plugins/builtin" / kind, allowed(kind, extra))
    assert problems == []


def test_steps_never_spawn_processes_themselves_so_the_runner_cannot_be_bypassed():
    """A step that called subprocess/os.system directly would run outside the workflow's runner (its sandbox,
    its environment policy). Steps use `run_cmd` (shell commands) or `support.git` (git)."""
    bad = []
    for path in python_files(SRC / "plugins/builtin/steps"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            if any(n.split(".")[0] in {"subprocess", "pty", "pexpect"} for n in names):
                bad.append(f"{path.relative_to(ROOT)}")
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                    and node.value.id == "os" and node.attr in {"system", "popen", "execv", "execvp", "spawnv"}:
                bad.append(f"{path.relative_to(ROOT)} (os.{node.attr})")
    assert bad == [], f"use run_cmd(ctx, ...) instead: {sorted(set(bad))}"


def test_the_package_top_level_has_only_the_expected_modules_and_folders():
    modules = {p.stem for p in SRC.glob("*.py")}
    packages = {p.name for p in SRC.iterdir() if p.is_dir() and p.name != "__pycache__"}
    assert modules <= TOP_LEVEL_MODULES, f"new top-level module(s) {sorted(modules - TOP_LEVEL_MODULES)}: " \
                                         "put them in a layer (cli/, a plugin folder) or add them on purpose"
    assert packages <= TOP_LEVEL_PACKAGES, f"new top-level folder(s): {sorted(packages - TOP_LEVEL_PACKAGES)}"


def test_no_module_grows_into_a_god_file():
    counts = {str(p.relative_to(ROOT)): len(p.read_text().splitlines()) for p in python_files(SRC)}
    too_long = {name: n for name, n in counts.items() if n > MAX_LINES}
    assert not too_long, f"over {MAX_LINES} lines, split by responsibility: {too_long}"


def test_the_plugin_folder_is_not_a_flat_pile_of_prefixed_files():
    flat = sorted(p.name for p in (SRC / "plugins/builtin").glob("*.py") if p.name != "__init__.py")
    assert flat == [], f"loose modules in plugins/builtin (use steps/, providers/, routing/, support/, tools/): {flat}"


def test_tests_mirror_the_code_layers():
    loose = sorted(p.name for p in TESTS.glob("test_*.py") if p.name != "test_architecture.py")
    assert loose == [], f"put these under tests/core, tests/plugins or tests/app: {loose}"
    assert {p.name for p in TESTS.iterdir() if p.is_dir() and p.name != "__pycache__"} <= {"core", "plugins", "app"}
