"""Which environment variables a command may see.

By default a command sees what it needs to find its tools and reach the network (PATH, HOME, locale,
proxies, CA bundles, the toolchain homes) and NOTHING ELSE: not AWS_*, not API keys, not tokens. Generated
code and the tests of a repository you cloned run in these commands.

This is not isolation: HOME is visible, so `~/.aws` and `~/.ssh` are still readable by the process.
Hiding files needs a sandbox (see the runner port)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from fnmatch import fnmatchcase

ALLOWED = (
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "TERM", "TMPDIR", "TMP", "TEMP", "TZ", "LANG", "LANGUAGE", "LC_*",
    "SYSTEMROOT", "PATHEXT", "COMSPEC", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
    # reaching the network from behind a proxy or a corporate certificate authority
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "no_proxy", "all_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "NODE_EXTRA_CA_CERTS",
    # where the toolchains live
    "JAVA_HOME", "GOPATH", "GOROOT", "CARGO_HOME", "RUSTUP_HOME", "NVM_DIR", "NODE_PATH", "PUB_CACHE",
    "FLUTTER_ROOT", "ANDROID_HOME", "ANDROID_SDK_ROOT", "FVM_*",
    # minifactory's own switches
    "FACTORY_FLUTTER", "MINIFACTORY_*",
)


def filtered(environ: Mapping[str, str], pass_env: Iterable[str] = ()) -> dict[str, str]:
    """The allowed variables of `environ`, plus any whose name matches a `pass_env` pattern (`MY_*`)."""
    patterns = (*ALLOWED, *pass_env)
    return {name: value for name, value in environ.items() if any(fnmatchcase(name, p) for p in patterns)}
