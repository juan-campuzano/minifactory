"""Secrets providers."""

from __future__ import annotations

import os

from minifactory.core.registry import register


@register("secrets", "env")
class EnvSecrets:
    """Secrets read from environment variables."""

    def get(self, name: str) -> str:
        try:
            return os.environ[name]
        except KeyError:
            raise KeyError(f"secret '{name}' is not set in the environment") from None
