"""The exact-match patch protocol used to edit files an agent did not write."""

import pytest

from minifactory.plugins.builtin.support.edits import PatchError, apply_patches, apply_reply, parse_patches


def reply(path, search, replace):
    return f"PATCH: {path}\n<<<<<<< SEARCH\n{search}\n=======\n{replace}\n>>>>>>> REPLACE\nEND_PATCH"


def test_parse_and_apply_a_patch(tmp_path):
    (tmp_path / "a.dart").write_text("int add(a, b) {\n  return a - b;\n}\n")
    assert apply_reply(tmp_path, reply("a.dart", "  return a - b;", "  return a + b;")) == ["a.dart"]
    assert (tmp_path / "a.dart").read_text() == "int add(a, b) {\n  return a + b;\n}\n"


def test_several_hunks_apply_in_order_to_the_same_file(tmp_path):
    (tmp_path / "f.txt").write_text("one\ntwo\nthree\n")
    text = ("PATCH: f.txt\n<<<<<<< SEARCH\none\n=======\n1\n>>>>>>> REPLACE\n"
            "<<<<<<< SEARCH\nthree\n=======\n3\n>>>>>>> REPLACE\nEND_PATCH")
    apply_reply(tmp_path, text)
    assert (tmp_path / "f.txt").read_text() == "1\ntwo\n3\n"


@pytest.mark.parametrize("search, why", [("missing", "found 0 times"), ("x", "found 2 times")])
def test_search_must_match_exactly_once_and_nothing_is_written_otherwise(tmp_path, search, why):
    (tmp_path / "f.txt").write_text("x\nx\nkeep\n")
    (tmp_path / "g.txt").write_text("ok\n")
    patches = {"g.txt": [("ok", "changed")], "f.txt": [(search, "y")]}  # g would succeed, f must not
    with pytest.raises(PatchError, match=why):
        apply_patches(tmp_path, patches)
    assert (tmp_path / "g.txt").read_text() == "ok\n"  # all-or-nothing
    assert (tmp_path / "f.txt").read_text() == "x\nx\nkeep\n"


def test_empty_search_creates_a_file_but_never_overwrites(tmp_path):
    apply_reply(tmp_path, reply("test/new_test.dart", "", "void main() {}"))
    assert (tmp_path / "test" / "new_test.dart").read_text() == "void main() {}\n"
    with pytest.raises(PatchError, match="already exists"):
        apply_reply(tmp_path, reply("test/new_test.dart", "", "other"))


def test_patching_a_missing_file_fails(tmp_path):
    with pytest.raises(PatchError, match="does not exist"):
        apply_reply(tmp_path, reply("nope.dart", "a", "b"))


def test_paths_cannot_escape_the_repo(tmp_path):
    with pytest.raises(ValueError, match="escapes"):
        apply_reply(tmp_path, reply("../evil.txt", "", "x"))


def test_allowed_prefixes_reject_edits_to_production_code_before_writing(tmp_path):
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "a.dart").write_text("a\n")
    text = reply("test/t.dart", "", "t") + "\n" + reply("lib/a.dart", "a", "b")
    with pytest.raises(PatchError, match="outside the allowed paths"):
        apply_reply(tmp_path, text, allowed_prefixes=["test/"])
    assert not (tmp_path / "test").exists() and (tmp_path / "lib" / "a.dart").read_text() == "a\n"


def test_file_blocks_and_patches_can_be_mixed(tmp_path):
    (tmp_path / "old.txt").write_text("hello\n")
    text = reply("old.txt", "hello", "bye") + "\nFILE: new.txt\ncontent\nEND_FILE"
    assert apply_reply(tmp_path, text) == ["new.txt", "old.txt"]


def test_a_reply_without_edits_parses_to_nothing():
    assert parse_patches("I could not find the bug.") == {}
