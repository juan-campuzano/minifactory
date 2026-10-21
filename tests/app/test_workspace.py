"""Workspaces: where a user's workflows live once the package is installed."""

import os
from pathlib import Path

import pytest

from minifactory import ask as R
from minifactory import templates, workspace
from minifactory.cli import commands as cli
from minifactory.cli import main
from minifactory.core import registry
from minifactory.core.errors import FactoryError, RoutingError
from minifactory.core.workflow import WorkflowSpec, load_workflow

registry.load_plugins()


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """No test may see the real ~/.config/minifactory."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.chdir(tmp_path)


def make_workspace(root: Path, **config) -> Path:
    workspace.init(root)
    if config:
        lines = "\n".join(f"{k}: {v}" for k, v in config.items())
        (root / "minifactory.yaml").write_text(f"schema_version: 1\n{lines}\n")
    return root


# -- finding it ------------------------------------------------------------------------------
def test_find_walks_up_like_git(tmp_path):
    root = make_workspace(tmp_path / "proj")
    deep = root / "a" / "b"
    deep.mkdir(parents=True)
    ws = workspace.find(deep)
    assert ws is not None and ws.root == root.resolve() and not ws.is_global


def test_global_workspace_is_the_fallback(tmp_path):
    make_workspace(tmp_path / "xdg" / "minifactory")
    ws = workspace.find(tmp_path)
    assert ws is not None and ws.is_global and ws.root == (tmp_path / "xdg" / "minifactory")


def test_no_workspace_anywhere(tmp_path):
    assert workspace.find(tmp_path) is None


def test_unknown_config_key_is_an_error(tmp_path):
    (tmp_path / "minifactory.yaml").write_text("workflow_dir: typo\n")
    with pytest.raises(workspace.ConfigError, match="workflow_dir"):
        workspace.load(tmp_path)


# -- init ------------------------------------------------------------------------------------
def test_init_is_idempotent_and_never_overwrites(tmp_path):
    root = tmp_path / "proj"
    assert set(workspace.init(root)) == {"minifactory.yaml", ".gitignore"}
    (root / "minifactory.yaml").write_text("schema_version: 1\nthreshold: 0.9\n")
    assert workspace.init(root) == []
    assert workspace.load(root).config.threshold == 0.9
    assert (root / "workflows").is_dir()


def test_init_command_with_a_template(tmp_path, capsys):
    assert main(["init", str(tmp_path / "p"), "--template", "java-migration-demo"]) == 0
    assert (tmp_path / "p" / "workflows" / "java-migration-demo.yaml").is_file()


# -- options: flag > minifactory.yaml > default ---------------------------------------------------
def parse(*argv):
    return cli._parser().parse_args(list(argv))


def test_config_fills_unset_options_and_flags_win(tmp_path):
    root = make_workspace(tmp_path / "proj", threshold=0.9, router="keyword", runs_dir="my_runs")
    os.chdir(root)
    args = parse("ask", "hi", "--threshold", "0.2")
    cli._use_workspace(args)
    assert args.threshold == 0.2  # flag
    assert args.router == "keyword" and args.runs_dir == "my_runs"  # config
    assert args.output_dir == "output"  # default


def test_without_a_workspace_defaults_apply_and_cwd_is_untouched(tmp_path):
    args = parse("ask", "hi")
    assert cli._use_workspace(args) is None
    assert (args.router, args.threshold, args.runs_dir) == ("jev", 0.7, ".minifactory/runs")
    assert Path.cwd() == tmp_path.resolve()


def test_relative_paths_resolve_from_the_workspace_root_even_from_a_subfolder(tmp_path):
    root = make_workspace(tmp_path / "proj")
    templates.copy("flutter-app-factory", root)
    sub = root / "deep" / "er"
    sub.mkdir(parents=True)
    os.chdir(sub)
    assert main(["validate", "flutter-app-factory"]) == 0
    assert Path.cwd() == root.resolve()  # `specs/` and `fixtures/` in the workflow now resolve


def test_an_explicit_file_path_is_relative_to_where_you_typed_it(tmp_path):
    root = make_workspace(tmp_path / "proj")
    templates.copy("java-migration-demo", root)
    os.chdir(root / "workflows")
    assert main(["validate", "java-migration-demo.yaml"]) == 0


# -- layers ----------------------------------------------------------------------------------
def test_project_workflows_win_over_global_ones_by_name(tmp_path):
    glob = make_workspace(tmp_path / "xdg" / "minifactory")
    proj = make_workspace(tmp_path / "proj")
    for root, text in ((glob, "global one"), (proj, "project one")):
        (root / "workflows" / "w.yaml").write_text(
            f"name: w\nroute:\n  description: {text}\n  intake: app-spec\n"
            "source: {use: static, with: {jobs: []}}\nsteps: []\n")
    ws = workspace.find(proj)
    found = R.discover(ws.workflow_dirs)
    assert found["w"].spec.route.description == "project one"


def test_packaged_templates_are_not_routable_until_copied(tmp_path):
    root = make_workspace(tmp_path / "proj")
    with pytest.raises(RoutingError, match="minifactory workflows copy"):
        R.discover(workspace.find(root).workflow_dirs)
    templates.copy("app-factory", root)
    assert "app-factory" in R.discover(workspace.find(root).workflow_dirs)


def test_unknown_workflow_name_lists_what_exists(tmp_path, capsys):
    make_workspace(tmp_path / "proj")
    os.chdir(tmp_path / "proj")
    assert main(["validate", "nope"]) == 2
    assert "not found" in capsys.readouterr().err


# -- templates -------------------------------------------------------------------------------
@pytest.mark.parametrize("name", sorted(templates.available()))
def test_every_packaged_template_is_a_valid_workflow(name, tmp_path):
    root = make_workspace(tmp_path / name)
    (path, *_) = templates.copy(name, root)
    load_workflow(path)  # validates plugins, params and references


def test_copy_is_idempotent_shares_assets_but_never_overwrites_your_edits(tmp_path):
    root = make_workspace(tmp_path / "p")
    first = templates.copy("flutter-app-factory", root)
    assert templates.copy("flutter-app-factory", root) == []  # nothing new, no error
    assert templates.copy("app-factory", root)  # a second template next to the first: no clash
    assert len(first) > 10
    mine = root / "workflows" / "flutter-app-factory.yaml"
    mine.write_text(mine.read_text() + "\n# my edit\n")
    with pytest.raises(FactoryError, match="would overwrite files you changed"):
        templates.copy("flutter-app-factory", root)
    assert "# my edit" in mine.read_text()
    with pytest.raises(FactoryError, match="unknown template"):
        templates.copy("nope", root)


def test_workflows_copy_needs_a_workspace(tmp_path, capsys):
    assert main(["workflows", "copy", "flutter-app-factory"]) == 2
    assert "minifactory init" in capsys.readouterr().err


# -- schema version --------------------------------------------------------------------------
def test_unknown_workflow_schema_version_is_rejected():
    base = {"name": "t", "source": {"use": "static", "with": {"jobs": []}}, "steps": []}
    assert WorkflowSpec.model_validate({**base, "schema_version": 1}).schema_version == 1
    with pytest.raises(ValueError, match="schema_version"):
        WorkflowSpec.model_validate({**base, "schema_version": 2})


def test_package_version_matches_pyproject():
    """Two places hold the version; the publish workflow checks the tag against pyproject."""
    import tomllib

    import minifactory

    root = Path(__file__).parents[2]
    declared = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    assert minifactory.__version__ == declared


def test_the_console_script_is_named_after_the_package_and_nothing_claims_the_bare_name_factory():
    """`factory` is also the import name of factory_boy: we must not install over it or its command."""
    import tomllib

    root = Path(__file__).parents[2]
    meta = tomllib.loads((root / "pyproject.toml").read_text())
    assert meta["project"]["scripts"] == {"minifactory": "minifactory.cli:main"}
    assert not (root / "src" / "factory").exists()
    assert list((root / "src").glob("*/__init__.py")) == [root / "src" / "minifactory" / "__init__.py"]
