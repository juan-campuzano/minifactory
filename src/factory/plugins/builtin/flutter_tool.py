"""`python -m factory.plugins.builtin.flutter_tool [--tool real|fake|auto] <flutter args>`.

Which flutter runs is explicit: `--tool` > $FACTORY_FLUTTER > `auto`. `auto` and `real` use the
real SDK on PATH and FAIL if it is missing: silently producing a fake project is worse than an
error. `fake` is the deterministic simulator for tests and offline demos only.
Standard library only: it also runs as a plain subprocess."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

MODES = ("auto", "real", "fake")


def command(tool: str | None = None) -> list[str]:
    mode = tool or os.environ.get("FACTORY_FLUTTER") or "auto"
    if mode not in MODES:
        raise ValueError(f"unknown flutter tool '{mode}' (expected one of {MODES})")
    if mode == "fake":
        return [sys.executable, "-m", "factory.plugins.builtin.fake_flutter"]
    real = shutil.which("flutter")
    if real is None:
        raise FileNotFoundError(
            "`flutter` is not on PATH. Install the Flutter SDK, or run a demo with tool: fake / FACTORY_FLUTTER=fake")
    return [real]


def main() -> int:
    args = sys.argv[1:]
    tool = None
    if args[:1] == ["--tool"]:
        tool, args = args[1], args[2:]
    try:
        cmd = command(tool)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 127
    return subprocess.run([*cmd, *args], check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
