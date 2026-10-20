"""Plugin registry. The core never imports a plugin; plugins register themselves."""

from __future__ import annotations

from importlib import import_module, metadata
from typing import Any, Callable, Iterable

from .errors import PluginNotFound

KINDS = ("step", "source", "executor", "scm", "llm", "secrets", "router", "intake")
_REG: dict[str, dict[str, Any]] = {k: {} for k in KINDS}


def register(kind: str, name: str) -> Callable[[Any], Any]:
    if kind not in _REG:
        raise ValueError(f"unknown plugin kind '{kind}' (expected one of {KINDS})")

    def deco(obj: Any) -> Any:
        if name in _REG[kind]:
            raise ValueError(f"{kind} '{name}' is already registered")
        _REG[kind][name] = obj
        return obj

    return deco


def get(kind: str, name: str) -> Any:
    try:
        return _REG[kind][name]
    except KeyError:
        raise PluginNotFound(
            f"{kind} '{name}' not found. Available: {sorted(_REG[kind]) or 'none'}"
        ) from None


def catalog() -> dict[str, list[str]]:
    return {k: sorted(v) for k, v in _REG.items()}


def load_plugins(extra_modules: Iterable[str] = ()) -> None:
    """Builtins + any installed package exposing the `minifactory.plugins` entry point +
    modules passed explicitly (handy for local experiments: --plugin my_module)."""
    import_module("minifactory.plugins.builtin")
    for ep in metadata.entry_points(group="minifactory.plugins"):
        ep.load()
    for module in extra_modules:
        import_module(module)
