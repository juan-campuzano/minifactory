"""A deliberately tiny expression language for `when:` and `${...}` templating.

Allowed: names, attribute access, literals, lists, comparisons, `in`, and/or/not.
No calls, no indexing, no arithmetic. If a workflow needs more than this, the logic
belongs in a plugin step written in code, not in YAML.
"""

from __future__ import annotations

import ast
import operator
import re
from typing import Any

from .errors import FactoryError


class ExprError(FactoryError):
    pass


class NS:
    """Read-only attribute view over nested dicts, so YAML can say `job.architecture`."""

    def __init__(self, data: dict[str, Any]):
        object.__setattr__(self, "_d", data)

    def __getattr__(self, key: str) -> Any:
        if key.startswith("__"):
            raise AttributeError(key)
        d = object.__getattribute__(self, "_d")
        if key not in d:
            raise ExprError(f"unknown name '{key}' (available: {sorted(d)})")
        v = d[key]
        return NS(v) if isinstance(v, dict) else v


_CMP = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}


def _ev(node: ast.AST, env: dict[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return _ev(node.body, env)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise ExprError(f"unknown name '{node.id}' (available: {sorted(env)})")
        return env[node.id]
    if isinstance(node, ast.Attribute):
        return getattr(_ev(node.value, env), node.attr)
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_ev(e, env) for e in node.elts]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _ev(node.operand, env)
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            return all(_ev(v, env) for v in node.values)
        return any(_ev(v, env) for v in node.values)
    if isinstance(node, ast.Compare):
        left = _ev(node.left, env)
        for op, comp in zip(node.ops, node.comparators):
            if type(op) not in _CMP:
                raise ExprError(f"unsupported operator {type(op).__name__}")
            right = _ev(comp, env)
            if not _CMP[type(op)](left, right):
                return False
            left = right
        return True
    raise ExprError(f"unsupported syntax: {type(node).__name__}")


def evaluate(expr: str, env: dict[str, Any]) -> Any:
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as e:
        raise ExprError(f"invalid expression '{expr}': {e.msg}") from None
    return _unwrap(_ev(tree, env))


def _unwrap(v: Any) -> Any:
    return object.__getattribute__(v, "_d") if isinstance(v, NS) else v


_TEMPLATE = re.compile(r"\$\{([^}]+)\}")


def render(value: Any, env: dict[str, Any]) -> Any:
    """Replace ${expr} inside strings (recursively). A string that is exactly one
    ${expr} keeps the native type of the result."""
    if isinstance(value, str):
        m = _TEMPLATE.fullmatch(value.strip())
        if m:
            return evaluate(m.group(1), env)
        return _TEMPLATE.sub(lambda m: str(evaluate(m.group(1), env)), value)
    if isinstance(value, dict):
        return {k: render(v, env) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, env) for v in value]
    return value
