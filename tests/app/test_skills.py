"""Skills: SKILL.md files added from a path or a GitHub URL (many at once) and given to agent steps.
No network: a GitHub clone is replaced by copying a prepared tree."""

import shutil
from pathlib import Path

import pytest

from minifactory import skills
from minifactory.cli import skills_cmd
from minifactory.cli.commands import main
from minifactory.core.context import StepContext
from minifactory.core.errors import FactoryError
from minifactory.core.models import Job

GOOD = "---\nname: {n}\ndescription: {d}\n---\nAlways {n}.\n"


def skill_file(root: Path, folder: str, name: str, desc: str = "does a thing") -> None:
    (root / folder).mkdir(parents=True, exist_ok=True)
    (root / folder / "SKILL.md").write_text(GOOD.format(n=name, d=desc))


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "home/.config"))
    monkeypatch.delenv("ZDOTDIR", raising=False)
    root = tmp_path / "ws"
    root.mkdir()
    (root / "minifactory.yaml").write_text("schema_version: 1\n")
    monkeypatch.chdir(root)
    return root


@pytest.fixture()
def many(tmp_path):
    tree = tmp_path / "pack"
    skill_file(tree, "skills/tdd", "tdd")
    skill_file(tree, "skills/review", "review")
    (tree / "skills/review/script.sh").write_text("echo hi\n")
    skill_file(tree, "node_modules/x", "ignored")
    (tree / "skills/broken").mkdir()
    (tree / "skills/broken/SKILL.md").write_text("---\nname: broken\n---\nno description\n")
    return tree


# -- reading ---------------------------------------------------------------------------------------
def test_parse_reads_frontmatter_and_falls_back_to_the_folder_name():
    s = skills.parse(GOOD.format(n="tdd", d="write tests first"), "x", Path("p"))
    assert (s.name, s.description, s.body) == ("tdd", "write tests first", "Always tdd.")
    assert skills.parse("---\ndescription: d\n---\nbody", "from-folder", Path("p")).name == "from-folder"


@pytest.mark.parametrize("text, reason", [("no frontmatter at all", "description"),
                                          ("---\ndescription: d\n---\n", "empty body"),
                                          ("---\nname: Bad Name\ndescription: d\n---\nb", "must match"),
                                          ("x" * (skills.MAX_SKILL_CHARS + 1), "limit")])
def test_unusable_skills_say_why(text, reason):
    with pytest.raises(skills.SkillError, match=reason):
        skills.parse(text, "ok-name", Path("p"))


def test_a_tree_gives_every_skill_and_a_line_per_skipped_file(many):
    found, skipped = skills.find_in_tree(many, "pack")
    assert sorted(s.name for s in found) == ["review", "tdd"]  # node_modules is not searched
    assert len(skipped) == 1 and "broken" in skipped[0] and "description" in skipped[0]


# -- URLs ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("url, ref, sub", [
    ("https://github.com/o/r", None, ""),
    ("github.com/o/r.git", None, ""),
    ("https://github.com/o/r/tree/dev/skills/a", "dev", "skills/a"),
    ("https://github.com/o/r/blob/main/a/SKILL.md", "main", "a/SKILL.md"),
    ("https://raw.githubusercontent.com/o/r/main/a/SKILL.md", "main", "a/SKILL.md")])
def test_github_urls(url, ref, sub):
    r = skills_cmd.parse_github(url)
    assert (r.clone_url, r.ref, r.subpath) == ("https://github.com/o/r.git", ref, sub)


@pytest.mark.parametrize("url", ["https://gitlab.com/o/r", "http://github.com/o/r", "https://github.com/o",
                                 "https://github.com/o/r/tree/main/../../etc", "https://github.com/o/r/issues/3",
                                 "not-a-thing"])
def test_other_urls_are_refused(url):
    with pytest.raises(FactoryError):
        skills_cmd.parse_github(url)


# -- add / list ------------------------------------------------------------------------------------
def test_adding_a_folder_with_many_skills_installs_them_all_but_only_the_text(ws, many, capsys):
    assert main(["skills", "add", str(many), "--yes"]) == 0
    out = capsys.readouterr().out
    assert sorted(skills.installed()) == ["review", "tdd"]
    assert not (ws / ".minifactory/skills/review/script.sh").exists()
    assert (ws / ".minifactory/skills/review/SKILL.md").is_file() and not (ws / "skills").exists()
    assert not (ws / "skills/review/script.sh").exists() and "1 other file(s)" in out and "broken" in out
    assert main(["skills", "add", str(many), "--yes"]) == 0  # idempotent
    assert "already installed" in capsys.readouterr().out


def test_without_a_terminal_it_refuses_unless_told_to_go_ahead(ws, many, capsys):
    assert main(["skills", "add", str(many)]) == 2
    assert skills.installed() == {} and "--yes" in capsys.readouterr().out


def test_a_different_skill_with_an_installed_name_is_not_overwritten(ws, many, tmp_path, capsys):
    main(["skills", "add", str(many), "--yes"])
    other = tmp_path / "other"
    skill_file(other, "tdd", "tdd", desc="something else")
    assert main(["skills", "add", str(other), "--yes"]) == 0
    assert "EXISTS with different content" in capsys.readouterr().out
    assert skills.installed()["tdd"].description == "does a thing"


def test_a_github_url_with_many_skills_is_cloned_and_loaded(ws, many, monkeypatch):
    calls = []

    def fake_git(*args, **kw):
        calls.append(args)
        shutil.copytree(many, args[-1])

    monkeypatch.setattr(skills_cmd, "git", fake_git)
    assert main(["skills", "add", "https://github.com/o/pack/tree/dev/skills", "--yes"]) == 0
    assert sorted(skills.installed()) == ["review", "tdd"]
    assert "--depth" in calls[0] and calls[0][calls[0].index("--branch") + 1] == "dev"


def test_a_failed_clone_is_a_clear_error(ws, monkeypatch, capsys):
    def boom(*args, **kw):
        raise skills_cmd.GitError("repository not found")

    monkeypatch.setattr(skills_cmd, "git", boom)
    assert main(["skills", "add", "https://github.com/o/nope", "--yes"]) == 2
    assert "could not fetch" in capsys.readouterr().err


def test_adding_needs_a_workspace_or_global(tmp_path, monkeypatch, many, capsys):
    monkeypatch.setenv("HOME", str(tmp_path / "h"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "h/.config"))
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    assert main(["skills", "add", str(many), "--yes"]) == 2
    assert main(["skills", "add", str(many), "--yes", "--global"]) == 0
    assert (tmp_path / "h/.config/minifactory/skills/tdd/SKILL.md").is_file()


# -- using them ------------------------------------------------------------------------------------
class Seen:
    prompts: list[str] = []

    def complete(self, system, prompt):
        self.prompts.append(prompt)
        return "FILE: a.txt\nhi\nEND_FILE"


def edit_with(tmp_path, names, events=None):
    events = [] if events is None else events
    from minifactory.plugins.builtin.steps.existing import Edit

    ctx = StepContext(job=Job(id="j", name="j"), work_dir=tmp_path, scm=None, llm=Seen(), secrets=None,
                      emit=lambda *a, **k: events.append((a, k)))
    ctx.repo_dir.mkdir(parents=True, exist_ok=True)
    from minifactory.plugins.builtin.support.git import git
    git("init", "-q", cwd=ctx.repo_dir)
    return Edit().run(ctx, Edit.Params(instruction="do it", skills=names))


def test_an_agent_step_shows_its_skills_to_the_llm_and_traces_them(ws, many, tmp_path):
    main(["skills", "add", str(many), "--yes"])
    Seen.prompts = []
    events: list = []
    assert edit_with(tmp_path / "run", ["tdd"], events).status == "ok"
    assert "### tdd\nAlways tdd." in Seen.prompts[0] and "Always review" not in Seen.prompts[0]
    assert any(a[0] == "skills_used" for a, _ in events)


def test_a_missing_skill_fails_the_step_before_any_llm_call(ws, tmp_path):
    Seen.prompts = []
    result = edit_with(tmp_path / "run", ["ghost"])
    assert result.status == "failed" and "not installed: ghost" in result.message and Seen.prompts == []


def test_too_much_skill_text_fails_instead_of_being_cut(ws, tmp_path):
    for i in range(3):
        skill_file(ws / ".minifactory/skills", f"big{i}", f"big{i}")
        (ws / f".minifactory/skills/big{i}/SKILL.md").write_text(GOOD.format(n=f"big{i}", d="d") + "x" * 9000)
    result = edit_with(tmp_path / "run", ["big0", "big1", "big2"])
    assert result.status == "failed" and "limit" in result.message


def test_skills_dir_can_be_changed_and_init_ignores_only_the_generated_runs(ws, many):
    (ws / "minifactory.yaml").write_text("schema_version: 1\nskills_dir: team/skills\n")
    assert main(["skills", "add", str(many), "--yes"]) == 0
    assert (ws / "team/skills/tdd/SKILL.md").is_file() and sorted(skills.installed()) == ["review", "tdd"]
    from minifactory import workspace

    workspace.init(ws / "fresh")
    assert (ws / "fresh/.gitignore").read_text().split() == [".minifactory/runs/", "output/"]  # skills stay committable
