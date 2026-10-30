---
title: Stack Profiles
description: How minifactory represents programming languages and toolchains as declarative YAML profiles.
---

All language knowledge in `minifactory` is data (`StackProfile`). Generic steps (`stack.detect`, `stack.scaffold`, `stack.check`, and `agent.*`) read the active stack profile so workflows remain language-agnostic.

Packaged profiles (`minifactory/profiles/`): `python`, `node`, `java` (JDK only), `flutter`, and `dart`. Add or override a stack by placing `<workspace>/stacks/<name>.yaml` in your workspace.

## `StackProfile` Schema

```yaml
name: ruby                                     # lowercase: ^[a-z][a-z0-9-]{0,30}$
description: "Ruby 3 with minitest"            # shown to the LLM when choosing a stack
requires: [ruby]                               # executables that must be on PATH
tools: []                                      # extra tools checked by `minifactory doctor`
detect: [Gemfile]                              # files that identify an existing repo (empty = never auto-detected)
manifest: Gemfile                              # dependency file included in agent context
seed_files:                                    # starter files written by `stack.scaffold`
  Gemfile: |
    source "https://rubygems.org"
scaffold: []                                   # shell commands run after seeding
commands:                                      # setup / analyze / test / test_files / format
  analyze: "ruby -c lib/*.rb"
  test: "ruby -Ilib -Itest -e 'Dir[\"test/**/*_test.rb\"].each { |f| require_relative f }'"
  test_files: "ruby -Ilib -Itest {paths}"      # used for targeted and reproduction test runs
source_globs: ["lib/**/*.rb"]
test_globs: ["test/**/*.rb"]
test_prefixes: ["test/"]                       # where tests live (`tests_only` & `qa` role confinement)
repro_test_path: test/factory_repro_test.rb
file_example: ["lib/{name}.rb", "test/{name}_test.rb"]
broken_test_patterns: ["SyntaxError", "LoadError"]
hints: |                                       # always shown (new and existing repos): how tests work
  Tests use minitest in test/*_test.rb.
new_project_hints: |                           # shown ONLY for new projects we scaffold
  Standard library only; no gems. Code in lib/{name}.rb.
```

## Template Placeholders

Commands, `seed_files`, `hints`, and `file_example` support literal placeholders:
- `{name}` — normalized `snake_case` project name.
- `{pkg}` — project name without underscores (e.g. for Java packages).
- `{paths}` — shell-quoted list of test file paths (for `commands.test_files`).
- `{python}` — shell-quoted path to the current Python interpreter.

## Authoring Rules

- **Analyze commands must never write into the repository** (e.g., avoid leaving `.pyc` or build artifacts that would end up in a pull request).
- **A test run that finds zero tests must exit non-zero**, or an empty project would pass the gate.
- **`broken_test_patterns`** lists compiler/syntax error strings that mean a reproduction test failed to compile/import rather than reproducing the bug.
