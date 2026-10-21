"""`minifactory doctor`, against a simulated machine: no test depends on what is installed here."""

import json

import pytest
import yaml
from rich.console import Console

from minifactory import doctor, workspace
from minifactory.cli import main
from minifactory.core import registry
from minifactory.core.workflow import WorkflowSpec

registry.load_plugins()


class FakeSystem(doctor.System):
    def __init__(self, tools=None, env=None, boto3=True, aws=("shared-credentials-file", "us-east-1"),
                 gh_code=0, aws_error=None):
        self.tools = tools or {}
        self.envvars = env or {}
        self.boto3, self._aws, self.gh_code, self.aws_error = boto3, aws, gh_code, aws_error

    def which(self, name):
        return f"/fake/bin/{name}" if name in self.tools else None

    def run(self, argv, timeout=10):
        if argv[:2] == ["gh", "auth"]:
            return self.gh_code, ""
        return 0, self.tools.get(argv[0], "")

    def getenv(self, name):
        return self.envvars.get(name)

    def has_module(self, name):
        return self.boto3 if name == "boto3" else True

    def aws(self):
        if self.aws_error:
            raise self.aws_error
        return self._aws

    def aws_identity(self):
        return doctor.mask_arn("arn:aws:iam::123456789012:user/juan")


FULL = {"python3": "Python 3.14.5", "node": "v24.15.0", "javac": "javac 21.0.12", "java": 'openjdk version "21"',
        "flutter": "┌────┐\n│ A new version is available │\n└────┘\nFlutter 3.47.4 • channel stable",
        "git": "git version 2.54.0", "gh": "gh version 2.93.0"}


def by_name(checks):
    return {(c.group, c.name): c for c in checks}


def ws_at(tmp_path):
    workspace.init(tmp_path)
    return workspace.load(tmp_path)


# -- core ------------------------------------------------------------------------------------
def test_without_a_workspace_it_warns_and_with_one_it_shows_where(tmp_path):
    assert doctor.core_checks(None)[-1].status == "warn"
    checks = by_name(doctor.core_checks(ws_at(tmp_path)))
    found = checks[("minifactory", "workspace")]
    assert found.status == "ok" and str(tmp_path) in found.detail


# -- toolchains --------------------------------------------------------------------------------
def test_a_missing_toolchain_is_information_with_an_install_hint_not_a_failure():
    sys_ = FakeSystem(tools={"python3": "Python 3.14.5"})
    checks = by_name(doctor.toolchain_checks(sys_, None))
    assert checks[("stacks", "python")].status == "ok" and "Python 3.14.5" in checks[("stacks", "python")].detail
    node = checks[("stacks", "node")]
    assert node.status == "info" and "not installed" in node.detail and "nodejs.org" in node.hint
    assert doctor.exit_code(list(checks.values())) == 0


def test_versions_skip_banners_and_do_not_repeat_the_tool_name():
    s = FakeSystem(tools=FULL)
    assert doctor._version(s, "flutter").startswith("Flutter 3.47.4")
    assert doctor._version(s, "node") == "node v24.15.0"
    assert doctor._version(s, "javac") == "javac 21.0.12"


# -- services and secrets ----------------------------------------------------------------------
def test_secrets_are_reported_as_present_never_printed():
    checks = doctor.service_checks(FakeSystem(tools=FULL, env={"TYPESAFE_API_KEY": "apikey_SUPERSECRET"}), online=False)
    blob = json.dumps(doctor.as_json(checks))
    assert "SUPERSECRET" not in blob and by_name(checks)[("router", "TYPESAFE_API_KEY")].detail == "set"


@pytest.mark.parametrize("system, status, text", [
    (FakeSystem(boto3=False), "info", "boto3 is not installed"),
    (FakeSystem(aws=(None, None)), "info", "no AWS credentials"),
    (FakeSystem(aws_error=RuntimeError("bad config")), "warn", "AWS configuration error"),
    (FakeSystem(aws=("sso", None)), "ok", "region not set"),
])
def test_bedrock_states(system, status, text):
    c = by_name(doctor.service_checks(system, online=False))[("llm", "bedrock")]
    assert c.status == status and text in c.detail


def test_online_checks_are_off_by_default_and_the_aws_account_is_masked():
    offline = by_name(doctor.service_checks(FakeSystem(tools=FULL), online=False))
    assert ("llm", "aws identity") not in offline and ("scm", "gh auth") not in offline
    online = by_name(doctor.service_checks(FakeSystem(tools=FULL), online=True))
    assert online[("llm", "aws identity")].detail == "arn:aws:iam::********9012:user/juan"
    assert online[("scm", "gh auth")].status == "ok"
    logged_out = by_name(doctor.service_checks(FakeSystem(tools=FULL, gh_code=1), online=True))
    assert logged_out[("scm", "gh auth")].status == "fail"


# -- what a workflow needs ---------------------------------------------------------------------
def spec_of(**parts):
    base = {"name": "w", "source": {"use": "static", "with": {"jobs": []}}, "steps": []}
    return WorkflowSpec.model_validate({**base, **parts})


def test_a_workflow_fails_the_doctor_when_its_providers_are_missing():
    spec = spec_of(providers={"scm": {"use": "github"}, "llm": {"use": "bedrock"}},
                   steps=[{"id": "f", "use": "flutter.analyze"}])
    bad = doctor.workflow_checks(FakeSystem(boto3=False), spec, online=False)
    names = {c.name: c for c in bad}
    assert names["boto3"].status == "fail" and names["gh"].status == "fail" and names["flutter"].status == "fail"
    assert doctor.exit_code(bad) == 1
    good = doctor.workflow_checks(FakeSystem(tools=FULL), spec, online=False)
    assert doctor.exit_code(good) == 0 and {c.status for c in good} == {"ok"}


def test_a_simulated_flutter_is_not_required():
    spec = spec_of(steps=[{"id": "f", "use": "flutter.analyze", "with": {"tool": "fake"}}])
    assert not [c for c in doctor.workflow_checks(FakeSystem(), spec, online=False) if c.name == "flutter"]


def test_a_workflow_that_fixes_its_stack_requires_that_toolchain_but_a_job_chosen_stack_does_not():
    fixed = spec_of(steps=[{"id": "s", "use": "stack.check", "with": {"check": "test", "stack": "python"}}])
    c = by_name(doctor.workflow_checks(FakeSystem(tools={}), fixed, online=False))
    assert list(k[1] for k in c) == ["stack python"] and next(iter(c.values())).status == "fail"
    dynamic = spec_of(steps=[{"id": "s", "use": "stack.check", "with": {"check": "test"}}])
    statuses = {x.status for x in doctor.workflow_checks(FakeSystem(tools={}), dynamic, online=False)}
    assert statuses == {"info"}  # whichever stack the request picks: only that one is needed


def test_openai_provider_needs_its_secret_in_the_environment():
    spec = spec_of(providers={"llm": {"use": "openai", "with": {"base_url": "http://x", "model": "m"}}})
    assert doctor.workflow_checks(FakeSystem(), spec, False)[0].status == "fail"
    assert doctor.workflow_checks(FakeSystem(env={"LLM_API_KEY": "x"}), spec, False)[0].status == "ok"


def test_mask_arn():
    assert doctor.mask_arn("arn:aws:iam::123456789012:user/x") == "arn:aws:iam::********9012:user/x"
    assert doctor.mask_arn("not-an-arn") == "not-an-arn"


# -- output and CLI -----------------------------------------------------------------------------
def test_render_groups_checks_and_summarises():
    console = Console(record=True, width=100, force_terminal=False)
    doctor.render(doctor.run_checks(FakeSystem(tools=FULL), None), console)
    out = console.export_text()
    assert "stacks" in out and "✓ python" in out and "0 failing" in out


def test_the_cli_prints_json_and_exits_non_zero_only_for_failures(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.chdir(tmp_path)
    assert main(["doctor", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert {"group", "name", "status", "detail", "hint"} <= set(data[0]) and data[0]["name"] == "version"


def test_doctor_for_a_workflow_checks_it_and_an_unknown_name_is_a_clear_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    workspace.init(tmp_path)
    (tmp_path / "workflows" / "w.yaml").write_text(yaml.safe_dump({
        "name": "w", "source": {"use": "static", "with": {"jobs": []}}, "steps": []}))
    monkeypatch.chdir(tmp_path)
    assert main(["doctor", "w", "--json"]) == 0
    capsys.readouterr()
    assert main(["doctor", "nope"]) == 2
    assert "not found" in capsys.readouterr().err
