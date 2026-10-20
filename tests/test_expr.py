import pytest

from minifactory.core.expr import NS, ExprError, evaluate, render

ENV = {
    "job": NS({"architecture": "clean", "java_current": 11}),
    "steps": NS({"build": {"status": "failed", "outputs": {"rc": 1}}}),
    "vars": NS({"target": "21"}),
}


def test_comparisons_and_logic():
    assert evaluate("job.architecture == 'clean'", ENV)
    assert evaluate("job.java_current < 17 and not job.architecture == 'other'", ENV)
    assert evaluate("steps.build.status in ['failed', 'skipped']", ENV)
    assert evaluate("steps.build.outputs.rc >= 1", ENV)


def test_render_keeps_type_for_single_expression():
    assert render("${steps.build.outputs.rc}", ENV) == 1
    assert render("branch-${vars.target}-x", ENV) == "branch-21-x"
    assert render({"a": ["${vars.target}"]}, ENV) == {"a": ["21"]}


@pytest.mark.parametrize("bad", ["__import__('os')", "job.architecture.upper()", "1 + 1", "job[0]"])
def test_no_calls_or_arithmetic(bad):
    with pytest.raises(ExprError):
        evaluate(bad, ENV)


def test_unknown_name_is_a_clear_error():
    with pytest.raises(ExprError, match="unknown name 'nope'"):
        evaluate("job.nope == 1", ENV)
