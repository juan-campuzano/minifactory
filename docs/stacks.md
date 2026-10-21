# Stack profiles: supporting a language

Everything language-specific lives in a YAML file, so supporting a new stack means adding a file, not code.
Packaged profiles: `python`, `node`, `java` (JDK only), `flutter` (`minifactory/profiles/`). Yours go in
`<workspace>/stacks/<name>.yaml`; a profile with the same name as a packaged one replaces it.

```yaml
name: ruby                          # lowercase, letters/digits/dashes
description: "Ruby 3 with minitest"  # shown to the LLM when it chooses a stack: say what the stack IS
requires: [ruby]                    # executables that must be on PATH (a clear error if missing)
detect: [Gemfile]                   # files that identify an EXISTING repo (empty = never auto-detected)
manifest: Gemfile                   # dependency file: shown to agents
seed_files:                         # written by `stack.scaffold` into a new project (never over existing files)
  Gemfile: |
    source "https://rubygems.org"
scaffold: []                        # shell commands run after seeding (e.g. `flutter create`)
commands:                           # analyze / test / test_files / format / setup; a missing one is skipped
  analyze: "ruby -c lib/*.rb"
  test: "ruby -Ilib -Itest -e 'Dir[\"test/**/*_test.rb\"].each { |f| require_relative f }'"
  test_files: "ruby -Ilib -Itest {paths}"      # must take {paths}: used for the reproduction test
source_globs: ["lib/**/*.rb"]
test_globs: ["test/**/*.rb"]
test_prefixes: ["test/"]            # a reproduction test may ONLY be written here
repro_test_path: test/factory_repro_test.rb
file_example: ["lib/{name}.rb", "test/{name}_test.rb"]   # shown to the planner so it follows this layout
broken_test_patterns: ["SyntaxError", "LoadError"]       # output meaning "the test did not run": not a reproduction
hints: |                            # true of the stack anywhere: how tests are written. Shown for existing repos too.
  Tests use minitest in test/*_test.rb.
new_project_hints: |                # layout and constraints for a NEW project only (never shown for an existing repo)
  Standard library only; no gems. Code in lib/{name}.rb.
```

Placeholders: `{name}` (project name, lower snake case), `{pkg}` (name without underscores), `{paths}` (test files),
`{python}` (this interpreter). They are replaced literally, so shell `${...}` and `{}` are safe.

Guidance for authors:
- **Prefer zero-dependency toolchains** (the standard test runner, no installs). Every dependency an LLM can add is
  supply-chain exposure and a slower, flakier gate. The packaged profiles use `unittest`, `node --test` and plain `javac`.
- **Commands must not write into the repository** (no bytecode, no build output that is not git-ignored): whatever
  they leave behind ends up in the pull request. The python profile checks syntax with `ast`, not `compileall`, for this reason.
- **A test run that finds no tests must fail**, or an empty project passes the gate.
- A Maven/Gradle Java project cannot use the packaged `java` profile (JDK only, never auto-detected). Write
  `stacks/java-maven.yaml` with `detect: [pom.xml]` and `mvn -q test` as the test command.
