"""`minifactory chat`: the conversation around `ask`. `run_ask` is replaced by a recorder, so these tests are about
the loop (commands, follow-up questions, errors, leaving), not about routing, which test_router.py covers."""

import argparse
import re

import pytest

from minifactory.cli import chat_cmd
from minifactory.cli.commands import main
from minifactory.core.errors import FactoryError, RoutingError


def plain(text):
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


@pytest.fixture()
def talk(monkeypatch):
    """talk(lines, ask=...) feeds `lines` to the prompt; `ask` is what run_ask does for each request."""

    def run(lines, ask=None, dirs=()):
        seen = []
        feed = iter(lines)

        def fake_input(prompt=""):
            try:
                item = next(feed)
            except StopIteration:
                raise EOFError from None
            if isinstance(item, BaseException):
                raise item
            return item

        def fake_ask(args):
            seen.append(args)
            if ask:
                return ask(args)
            return 0

        monkeypatch.setattr("builtins.input", fake_input)
        monkeypatch.setattr(chat_cmd, "run_ask", fake_ask)
        monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
        monkeypatch.setattr("sys.stdout.isatty", lambda: True, raising=False)
        args = argparse.Namespace(workflow_dirs=list(dirs), router="keyword", threshold=0.7, runs_dir="r",
                                  output_dir="o", plain=True, plugin=[], owner=None, public=False, yes=True,
                                  dry_run=True, output="x")
        return chat_cmd.run_chat(args), seen

    return run


def test_it_needs_a_terminal(capsys):
    assert main(["chat"]) == 2  # pytest has no TTY
    assert "needs a terminal" in capsys.readouterr().err


def test_every_line_is_one_request_and_ctrl_d_leaves(talk):
    rc, seen = talk(["review PR 7 in acme/app", "", "add a flag to acme/app"])
    assert rc == 0 and [a.request for a in seen] == ["review PR 7 in acme/app", "add a flag to acme/app"]


def test_the_safety_prompts_of_ask_can_never_be_switched_off_from_the_conversation(talk):
    _, seen = talk(["do something in acme/app"])
    assert seen[0].yes is False and seen[0].dry_run is False and seen[0].output is None  # even if the args said so


def test_slash_commands_do_not_make_requests_and_exit_stops(talk, capsys):
    rc, seen = talk(["/help", "/nonsense", "/exit", "never read"])
    out = plain(capsys.readouterr().out)
    assert rc == 0 and seen == [] and "Type what you need" in out and "unknown command /nonsense" in out


def test_a_missing_detail_is_asked_for_and_added_to_the_request(talk):
    def ask(args):
        if "acme/app" not in args.request:
            raise RoutingError("name the repository as owner/name")
        return 0

    rc, seen = talk(["fix the login crash", "it is in acme/app"], ask=ask)
    assert [a.request for a in seen] == ["fix the login crash", "fix the login crash\nit is in acme/app"]


def test_an_empty_answer_drops_the_request_and_the_chat_goes_on(talk):
    def ask(args):
        raise RoutingError("no workflow fits this request")

    rc, seen = talk(["make me a sandwich", "", "review PR 7 in acme/app", ""], ask=ask)
    assert rc == 0 and len(seen) == 2


def test_it_does_not_insist_forever(talk):
    def ask(args):
        raise RoutingError("still vague")

    _, seen = talk(["x y z", "more", "even more"], ask=ask)
    assert len(seen) == chat_cmd.MAX_FOLLOW_UPS + 1


def test_an_error_is_reported_and_the_conversation_continues(talk, capsys):
    def ask(args):
        if "boom" in args.request:
            raise FactoryError("gh is not logged in")
        return 0

    _, seen = talk(["boom", "fine"], ask=ask)
    assert len(seen) == 2 and "gh is not logged in" in plain(capsys.readouterr().out)


def test_ctrl_c_cancels_the_running_request_but_not_the_chat(talk, capsys):
    def ask(args):
        if "slow" in args.request:
            raise KeyboardInterrupt
        return 0

    rc, seen = talk(["slow one", KeyboardInterrupt(), "next"], ask=ask)  # 2nd: Ctrl-C at the empty prompt
    assert rc == 0 and [a.request for a in seen] == ["slow one", "next"] and "cancelled" in capsys.readouterr().out


def test_workflows_lists_what_ask_could_choose(talk, tmp_path, capsys):
    from minifactory import templates

    templates.copy("review-pr", tmp_path, "workflows")
    talk(["/workflows"], dirs=[tmp_path / "workflows"])
    out = plain(capsys.readouterr().out)
    assert "review-pr" in out and "e.g. review PR 285" in out
