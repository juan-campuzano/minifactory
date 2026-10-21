"""TLS for the HTTP providers."""

from __future__ import annotations

import ssl


def ssl_context() -> ssl.SSLContext:
    """TLS context for our HTTP providers. python.org builds on macOS ship without root
    certificates (CERTIFICATE_VERIFY_FAILED), so prefer certifi's bundle when it is installed."""
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())
