"""Where the result goes: a plain local folder, or a new GitHub repo + PR (via a fake `gh`)."""

import json
import subprocess
from pathlib import Path

import pytest

from minifactory import ask as R
from minifactory.core import registry
from minifactory.core.errors import RoutingError
from minifactory.core.workflow import WorkflowSpec
from minifactory.plugins.builtin.providers.github import GitHub
from minifactory.plugins.builtin.providers.scm import LocalDir
from minifactory.plugins.builtin.steps.agent import MAX_FEATURES, AppPlan
from minifactory.plugins.builtin.support.git import git

registry.load_plugins()


def generate(provider, workdir: Path, repo="expense_tracker"):
    """What the workflow does around the provider: init, create files, deliver."""
    provider.init_repo(repo, workdir)
    (workdir / "lib").mkdir()
    (workdir / "lib" / "main.dart").write_text("void main() {}\n")
    return provider.push_and_open_pr(repo, workdir, f"factory/{repo}", "feat: expense tracker",
                                     "An app.\n\n### Factory notes\n- coverage 50%")


# -- local folder ----------------------------------------------------------------------------
def test_local_dir_delivers_a_plain_git_repo_on_main_with_notes_in_the_readme(tmp_path):
    out = tmp_path / "out"
    ref = generate(LocalDir(dir=str(out)), tmp_path / "work")
    folder = out / "expense_tracker"
    assert ref == f"file://{folder.resolve()}"
    assert (folder / "lib" / "main.dart").exists()
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=folder) == "main"
    assert "Factory notes" in (folder / "README.md").read_text()
    assert git("status", "--porcelain", cwd=folder) == ""


def test_local_dir_does_not_ship_git_ignored_build_output(tmp_path):
    provider = LocalDir(dir=str(tmp_path / "out"))
    provider.init_repo("app", tmp_path / "work")
    (tmp_path / "work" / ".gitignore").write_text("build/\n")
    (tmp_path / "work" / "build").mkdir()
    (tmp_path / "work" / "build" / "huge.bin").write_text("x")
    (tmp_path / "work" / "main.dart").write_text("void main() {}\n")
    provider.push_and_open_pr("app", tmp_path / "work", "b", "t", "")
    assert (tmp_path / "out" / "app" / "main.dart").exists()
    assert not (tmp_path / "out" / "app" / "build").exists()


def test_local_dir_refuses_to_overwrite_and_guard_sees_it(tmp_path):
    provider = LocalDir(dir=str(tmp_path / "out"))
    generate(provider, tmp_path / "work")
    assert provider.branch_exists("expense_tracker", "factory/x") is True
    with pytest.raises(FileExistsError):
        provider.init_repo("expense_tracker", tmp_path / "work2")


def test_local_dir_with_nothing_generated_delivers_nothing(tmp_path):
    provider = LocalDir(dir=str(tmp_path / "out"))
    provider.init_repo("empty", tmp_path / "work")
    assert provider.push_and_open_pr("empty", tmp_path / "work", "b", "t", "") is None
    assert not (tmp_path / "out" / "empty").exists()


# -- GitHub, through a fake gh ---------------------------------------------------------------
class FakeGh:
    """Emulates the few `gh` commands the provider uses, backed by local bare repos."""

    def __init__(self, root: Path, existing=()):
        self.root, self.calls, self.repos, self.prs = root, [], set(existing), []

    def __call__(self, argv, cwd):
        self.calls.append(argv)
        assert argv[0] == "gh"
        cmd = argv[1:]
        if cmd[:2] == ["api", "user"]:
            return 0, "juan", ""
        if cmd[0] == "api":  # repos/<owner>/<repo>/branches/<branch>
            _, _, repo, _, branch = cmd[1].split("/", 4)  # branches may contain "/"
            bare = self.root / f"{repo}.git"
            ok = bare.exists() and subprocess.run(
                ["git", "--git-dir", str(bare), "rev-parse", "--verify", branch],
                capture_output=True).returncode == 0
            return (0, "{}", "") if ok else (1, "", "gh: Not Found (HTTP 404)")
        if cmd[:2] == ["repo", "view"] and "--json" not in cmd:
            return (0, "", "") if cmd[2].split("/")[1] in self.repos else (1, "", "not found")
        if cmd[:2] == ["repo", "view"]:
            return 0, "main", ""
        if cmd[:2] == ["repo", "create"]:
            name = cmd[2].split("/")[1]
            self.repos.add(name)
            seed = self.root / f"seed_{name}"
            seed.mkdir(parents=True)
            git("init", "--quiet", "-b", "main", cwd=seed)
            (seed / "README.md").write_text(f"# {name}\n")
            git("add", "-A", cwd=seed)
            git("-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "Initial commit", cwd=seed)
            git("clone", "--quiet", "--bare", str(seed), str(self.root / f"{name}.git"))
            return 0, "", ""
        if cmd[:2] == ["repo", "clone"]:
            git("clone", "--quiet", str(self.root / f"{cmd[2].split('/')[1]}.git"), cmd[3])
            return 0, "", ""
        if cmd[:2] == ["pr", "list"]:
            return 0, json.dumps(self.prs), ""
        if cmd[:2] == ["pr", "create"]:
            return 0, "https://github.com/juan/expense_tracker/pull/1", ""
        raise AssertionError(f"unexpected gh call: {argv}")


def test_github_creates_a_private_repo_pushes_a_branch_and_opens_a_pr(tmp_path):
    gh = FakeGh(tmp_path / "remote")
    provider = GitHub(runner=gh)
    url = generate(provider, tmp_path / "work")
    assert url == "https://github.com/juan/expense_tracker/pull/1"
    create = next(c for c in gh.calls if c[1:3] == ["repo", "create"])
    assert create[3] == "juan/expense_tracker" and "--private" in create and "--add-readme" in create
    pr = next(c for c in gh.calls if c[1:3] == ["pr", "create"])
    assert pr[pr.index("--base") + 1] == "main" and pr[pr.index("--head") + 1] == "factory/expense_tracker"
    assert "Factory notes" in pr[pr.index("--body") + 1]
    assert provider.branch_exists("expense_tracker", "factory/expense_tracker") is True
    assert "private" in provider.target("expense_tracker")


def test_github_public_and_explicit_owner(tmp_path):
    gh = FakeGh(tmp_path / "remote")
    provider = GitHub(owner="acme", private=False, runner=gh)
    assert "PUBLIC" in provider.target("x") and provider.target("x").startswith("github.com/acme/x")
    provider.init_repo("x", tmp_path / "work")
    create = next(c for c in gh.calls if c[1:3] == ["repo", "create"])
    assert create[3] == "acme/x" and "--public" in create


def test_github_refuses_an_existing_repo_and_guard_handles_a_missing_one(tmp_path):
    gh = FakeGh(tmp_path / "remote", existing={"taken"})
    provider = GitHub(runner=gh)
    with pytest.raises(FileExistsError, match="juan/taken"):
        provider.init_repo("taken", tmp_path / "work")
    assert provider.branch_exists("missing", "factory/missing") is False  # 404 is not an error
    assert provider.open_prs("missing") == []


def test_github_unexpected_gh_failure_is_loud(tmp_path):
    provider = GitHub(runner=lambda argv, cwd: (1, "", "HTTP 500 boom"))
    with pytest.raises(RuntimeError, match="boom"):
        provider.branch_exists("x", "b")


# -- choosing the output ---------------------------------------------------------------------
def base_spec():
    return WorkflowSpec.model_validate({
        "name": "t", "source": {"use": "static", "with": {"jobs": []}},
        "providers": {"scm": {"use": "local-git", "with": {"remotes_dir": "r", "prs_dir": "p"}}},
        "steps": []})


def test_with_output_swaps_only_the_scm_provider():
    local = R.with_output(base_spec(), "local", output_dir="/tmp/x")
    assert local.providers["scm"].use == "local-dir" and local.providers["scm"].with_ == {"dir": "/tmp/x"}
    hub = R.with_output(base_spec(), "github", owner="acme", public=True)
    assert hub.providers["scm"].use == "github"
    assert hub.providers["scm"].with_ == {"private": False, "owner": "acme"}
    assert R.with_output(base_spec(), "github").providers["scm"].with_ == {"private": True}
    with pytest.raises(RoutingError):
        R.with_output(base_spec(), "ftp")


def test_a_plan_cannot_outgrow_the_implement_budget():
    feature = {"id": "a", "title": "t", "files": ["lib/a.dart"]}
    AppPlan.model_validate({"features": [feature] * MAX_FEATURES})
    with pytest.raises(ValueError):
        AppPlan.model_validate({"features": [feature] * (MAX_FEATURES + 1)})
