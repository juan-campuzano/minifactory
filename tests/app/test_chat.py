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
        run.sessions = sessions = []
        feed = iter(lines)

        def fake_input(prompt=""):
            try:
                item = next(feed)
            except StopIteration:
                raise EOFError from None
            if isinstance(item, BaseException):
                raise item
            return item

        def fake_ask(args, session=None):
            seen.append(args)
            sessions.append(session)
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


# -- memory ------------------------------------------------------------------------------------------
from minifactory.cli.chat_memory import Session  # noqa: E402
from minifactory.core.models import Artifact, Job, JobResult, StepRecord  # noqa: E402


def test_the_last_repo_and_pr_fill_what_a_request_leaves_out():
    s = Session()
    assert s.fill("review it") == ("review it", "")  # nothing known yet
    s.drafted("review-pr", Job(id="j", name="acme/app", attrs={"repo": "acme/app", "pr": 7}))
    assert s.fill("add a flag") == ("add a flag in acme/app", "acme/app")  # the PR number is only for PR talk
    assert s.fill("review the PR again") == ("review the PR again in acme/app (#7)", "acme/app #7")
    assert s.fill("review PR 8") == ("review PR 8 in acme/app", "acme/app")  # its own number wins
    assert s.fill("review PR 8 in other/thing") == ("review PR 8 in other/thing", "")  # its own repo wins
    s.forget()
    assert s.fill("review the PR again")[1] == ""


def test_a_job_without_a_repository_is_not_a_context():
    s = Session()
    s.drafted("app-factory", Job(id="todo", name="todo", attrs={"description": "a todo app"}))
    assert s.fill("add a flag") == ("add a flag", "")


def test_a_finished_run_is_remembered_with_its_outcome_and_report():
    s = Session()
    s.drafted("review-pr", Job(id="j", name="acme/app", attrs={"repo": "acme/app", "pr": 7}))
    assert s.turns[-1].outcome == "not run"
    s.finished([JobResult(job_id="j", outcome="succeeded", artifacts=[Artifact(kind="pr_comment", ref="https://x/1")],
                          steps=[StepRecord(id="review", outputs={"report": "## Review\nall good"})])])
    turn = s.turns[-1]
    assert (turn.outcome, turn.detail, turn.report) == ("succeeded", "https://x/1", "## Review\nall good")
    assert "review-pr" in s.lines()[0] and "succeeded" in s.lines()[0]


def test_the_chat_retries_with_what_it_remembers_before_bothering_the_user(talk, capsys):
    def ask(args):
        session = talk.sessions[-1]
        if "acme/app" not in args.request:
            raise RoutingError("name the pull request as owner/name and its number")
        session.drafted("review-pr", Job(id="j", name="acme/app", attrs={"repo": "acme/app", "pr": 7}))

    rc, seen = talk(["review PR 7 in acme/app", "review the PR again"], ask=ask)
    assert [a.request for a in seen] == ["review PR 7 in acme/app", "review the PR again",
                                        "review the PR again in acme/app (#7)"]
    assert "acme/app #7 from earlier" in " ".join(plain(capsys.readouterr().out).split())  # it says what it filled in


def test_what_memory_cannot_fill_is_asked_and_forgetting_really_forgets(talk):
    def ask(args):
        if "acme/app" not in args.request:
            raise RoutingError("name the repository")
        talk.sessions[-1].drafted("fix-bug", Job(id="j", name="acme/app", attrs={"repo": "acme/app"}))

    # after /forget the same request has to be completed by the user
    rc, seen = talk(["fix it in acme/app", "/forget", "fix it again", "in acme/app"], ask=ask)
    assert [a.request for a in seen] == ["fix it in acme/app", "fix it again", "fix it again\nin acme/app"]


def test_history_and_last_show_what_happened(talk, capsys):
    def ask(args):
        talk.sessions[-1].drafted("review-pr", Job(id="j", name="acme/app", attrs={"repo": "acme/app", "pr": 7}))
        talk.sessions[-1].finished([JobResult(job_id="j", outcome="succeeded", steps=[
            StepRecord(id="review", outputs={"report": "THE REPORT"})])])

    talk(["review PR 7 in acme/app", "/history", "/last"], ask=ask)
    out = plain(capsys.readouterr().out)
    assert "1." in out and "review-pr" in out and "THE REPORT" in out and "pr: 7" in out


def test_a_real_run_tells_the_session_how_it_ended(tmp_path, monkeypatch):
    """The wiring in ask_flow: run_ask(args, session) records the drafted job and the result."""
    from minifactory import ask as routing
    from minifactory.cli.ask_flow import run_ask
    from minifactory.core import registry
    from minifactory.core.context import Step
    from minifactory.core.models import StepResult

    @registry.register("step", "t.chatmark")
    class Mark(Step):
        def run(self, ctx, p):
            return StepResult.ok("done")

    @registry.register("intake", "t.chatintake")
    class Intake:
        def build(self, request, llm):
            return Job(id="j1", name="acme/app", attrs={"repo": "acme/app", "pr": 3})

    folder = tmp_path / "wf"
    folder.mkdir()
    (folder / "review-pr.yaml").write_text(
        "name: review-pr\nroute: {description: review a pull request, intake: t.chatintake, delivery: fixed}\n"
        "source: {use: static, with: {jobs: []}}\nproviders:\n  llm: {use: fixture, with: {path: fixtures/flutter}}\n"
        "steps:\n  - id: mark\n    use: t.chatmark\n")
    session = Session()
    args = argparse.Namespace(request="review a pull request", workflow_dirs=[folder], router="keyword", threshold=0.1,
                              yes=True, dry_run=False, output=None, output_dir="o", owner=None, public=False,
                              runs_dir=str(tmp_path / "runs"), plain=True, plugin=[])
    assert routing.discover([folder]) and run_ask(args, session) == 0
    assert [(t.workflow, t.outcome, t.job.attrs["pr"]) for t in session.turns] == [("review-pr", "succeeded", 3)]
