import pytest

from minifactory.core import registry
from minifactory.core.errors import PluginNotFound, WorkflowError
from minifactory.core.workflow import WorkflowSpec, validate_spec

registry.load_plugins()


def spec(steps, **extra):
    base = {"name": "t", "source": {"use": "static", "with": {"jobs": []}}, "steps": steps}
    return WorkflowSpec.model_validate({**base, **extra})


def test_unknown_step_plugin():
    with pytest.raises(PluginNotFound, match="nope.step"):
        validate_spec(spec([{"id": "a", "use": "nope.step"}]))


def test_typo_in_params_fails_before_running():
    with pytest.raises(WorkflowError, match="cmdd"):
        validate_spec(spec([{"id": "a", "use": "shell.run", "with": {"cmd": "x", "cmdd": "y"}}]))


def test_missing_required_param():
    with pytest.raises(WorkflowError, match="cmd"):
        validate_spec(spec([{"id": "a", "use": "shell.run"}]))


def test_step_needs_a_provider():
    with pytest.raises(WorkflowError, match="'scm' provider"):
        validate_spec(spec([{"id": "a", "use": "scm.clone"}]))


def test_reference_to_later_step_is_rejected():
    steps = [
        {"id": "a", "use": "shell.run", "when": "steps.b.status == 'ok'", "with": {"cmd": "true"}},
        {"id": "b", "use": "shell.run", "with": {"cmd": "true"}},
    ]
    with pytest.raises(WorkflowError, match="does not run before"):
        validate_spec(spec(steps))


def test_duplicate_ids_and_bad_when_syntax():
    with pytest.raises(WorkflowError, match="duplicate"):
        validate_spec(spec([{"id": "a", "use": "shell.run", "with": {"cmd": "x"}},
                            {"id": "a", "use": "shell.run", "with": {"cmd": "x"}}]))
    with pytest.raises(WorkflowError, match="invalid when"):
        validate_spec(spec([{"id": "a", "use": "shell.run", "when": "1 +", "with": {"cmd": "x"}}]))


def test_templated_values_skip_static_type_checks():
    # timeout is an int, but the template is resolved at runtime, so load-time must allow it
    validate_spec(spec([{"id": "a", "use": "shell.run",
                         "with": {"cmd": "x", "timeout": "${vars.t}"}}], vars={"t": 5}))
