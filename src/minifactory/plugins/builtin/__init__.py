"""Builtin plugins. Importing this package registers them; the core never imports it
directly (registry.load_plugins does)."""

from . import (  # noqa: F401
    intakes,
    providers_bedrock,
    providers_github,
    providers_llm,
    providers_misc,
    providers_scm,
    routers,
    steps_agent,
    steps_build,
    steps_existing,
    steps_flutter,
    steps_scm,
    steps_stack,
    steps_workflows,
)
