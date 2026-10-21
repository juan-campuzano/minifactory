"""Builtin plugins. Importing this package registers them; the core never imports it
directly (registry.load_plugins does)."""

from . import providers, routing, steps  # noqa: F401
