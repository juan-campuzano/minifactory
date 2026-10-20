"""A tiny deterministic stand-in for the flutter CLI: `create`, `analyze`, `test`.

It checks a handful of rules that real Flutter also enforces (balanced brackets, missing
imports, removed APIs) so the factory's gates, repair loop and coverage phase can be
exercised without the SDK. Standard library only."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

MAIN_DART = """import 'package:flutter/material.dart';

void main() => runApp(const MaterialApp(home: Text('hello')));
"""
WIDGET_TEST = """import 'package:flutter_test/flutter_test.dart';
import 'package:{name}/main.dart';

void main() {{
  test('main exists', () => expect(main, isNotNull));
}}
"""
REMOVED_APIS = ("FlatButton", "RaisedButton")
PAIRS = {"(": ")", "{": "}", "[": "]"}


def _dart_files(root: Path, folder: str) -> list[Path]:
    return sorted((root / folder).glob("**/*.dart"))


def _problems(root: Path) -> list[str]:
    problems: list[str] = []
    for path in _dart_files(root, "lib") + _dart_files(root, "test"):
        text, rel = path.read_text(), path.relative_to(root)
        for opener, closer in PAIRS.items():
            if text.count(opener) != text.count(closer):
                problems.append(f"error • Expected to find '{closer}' • {rel} • expected_token")
        uses_flutter = re.search(r"\b(StatelessWidget|StatefulWidget|MaterialApp)\b", text)
        if uses_flutter and "package:flutter/material.dart" not in text:
            problems.append(f"error • Undefined class 'StatelessWidget' • {rel} • undefined_class")
        for api in REMOVED_APIS:
            if api in text:
                problems.append(f"error • The method '{api}' isn't defined • {rel} • undefined_method")
    return problems


def analyze(root: Path) -> int:
    problems = _problems(root)
    print("\n".join(f"  {p}" for p in problems) or "No issues found!")
    if problems:
        print(f"{len(problems)} issues found.")
    return 1 if problems else 0


def _write_lcov(root: Path) -> None:
    tests = "\n".join(p.read_text() for p in _dart_files(root, "test"))
    records = []
    for path in _dart_files(root, "lib"):
        rel = path.relative_to(root / "lib").as_posix()
        hit = 10 if f"/{rel}'" in tests else 0
        records.append(f"SF:lib/{rel}\nLF:10\nLH:{hit}\nend_of_record")
    (root / "coverage").mkdir(exist_ok=True)
    (root / "coverage" / "lcov.info").write_text("\n".join(records) + "\n")


def test(root: Path, coverage: bool) -> int:
    if not (root / "test").is_dir() or not _dart_files(root, "test"):
        print('Test directory "test" not found.')
        return 1
    if (rc := analyze(root)) != 0:
        print("Some tests failed.")
        return rc
    if coverage:
        _write_lcov(root)
    print("All tests passed!")
    return 0


def create(root: Path, name: str) -> int:
    (root / "lib").mkdir(exist_ok=True)
    (root / "test").mkdir(exist_ok=True)
    (root / ".gitignore").write_text("/coverage/\n/build/\n.dart_tool/\n")
    (root / "pubspec.yaml").write_text(f"name: {name}\nenvironment:\n  sdk: '>=3.0.0 <4.0.0'\n")
    (root / "lib" / "main.dart").write_text(MAIN_DART)
    (root / "test" / "widget_test.dart").write_text(WIDGET_TEST.format(name=name))
    print(f"Creating project {name}... All done!")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fake_flutter")
    sub = parser.add_subparsers(dest="cmd", required=True)
    make = sub.add_parser("create")
    make.add_argument("--project-name", required=True)
    make.add_argument("--org", default="com.example")
    make.add_argument("target", nargs="?", default=".")
    sub.add_parser("analyze")
    run_tests = sub.add_parser("test")
    run_tests.add_argument("--coverage", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.target if args.cmd == "create" else ".").resolve()
    if args.cmd == "create":
        return create(root, args.project_name)
    if args.cmd == "analyze":
        return analyze(root)
    return test(root, args.coverage)


if __name__ == "__main__":
    sys.exit(main())
