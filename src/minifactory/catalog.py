"""A description of what can be built with the registered plugins, generated from the registry
itself (so it is never stale): which steps exist, what parameters they take, which providers a
workflow can configure. It is what the workflow-drafting agent reads, and `plugins --schema` prints."""

from __future__ import annotations

import inspect
from typing import Any

from .core import registry

# Constructor arguments that are injected by the engine or exist only for tests: not for a workflow author.
_INTERNAL = {"self", "secrets", "client", "transport", "runner"}


def _first_paragraph(obj: Any) -> str:
    """The class's OWN docstring (an inherited one would describe the base class, not the plugin)."""
    doc = inspect.cleandoc(obj.__dict__.get("__doc__") or "")
    return " ".join(doc.split("\n\n")[0].split())


def _type(schema: dict[str, Any]) -> str:
    if "enum" in schema:
        return "|".join(map(str, schema["enum"]))
    if "anyOf" in schema:
        return " | ".join(t for t in (_type(s) for s in schema["anyOf"]) if t != "null") or "null"
    if schema.get("type") == "array":
        return f"list[{_type(schema.get('items', {})) or 'any'}]"
    if "$ref" in schema:
        return "object"
    return str(schema.get("type", "any"))


def _step_params(cls: Any) -> list[dict[str, Any]]:
    schema = cls.Params.model_json_schema()
    required = set(schema.get("required", []))
    return [{"name": name, "type": _type(spec), "required": name in required,
             **({"default": spec["default"]} if "default" in spec else {})}
            for name, spec in schema.get("properties", {}).items()]


def _init_params(cls: Any) -> list[dict[str, Any]]:
    out = []
    for name, p in inspect.signature(cls.__init__).parameters.items():
        if name in _INTERNAL or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        out.append({"name": name, "required": p.default is p.empty,
                    **({} if p.default is p.empty else {"default": p.default})})
    return out


def describe() -> dict[str, Any]:
    """{'steps': {name: {doc, needs, params}}, '<kind>': {name: {doc, params}}} for every plugin."""
    out: dict[str, Any] = {"steps": {}}
    for name in registry.catalog()["step"]:
        cls = registry.get("step", name)
        out["steps"][name] = {"doc": _first_paragraph(cls), "needs": list(cls.needs), "params": _step_params(cls)}
    for kind in ("scm", "llm", "secrets", "source", "executor", "router", "intake"):
        out[kind] = {name: {"doc": _first_paragraph(registry.get(kind, name)),
                            "params": _init_params(registry.get(kind, name))}
                     for name in registry.catalog()[kind]}
    return out


FORMAT_GUIDE = """\
# How a workflow is written

A workflow is one YAML file. Only the keys below exist; anything else is an error.

```yaml
name: my-workflow                 # required, unique
route:                            # optional: makes `minifactory ask` able to choose it
  description: one sentence on when to use this workflow
  not_for: [things it must not be used for]
  examples: ["a sample request"]
  needs: what a request must contain for it to start
  intake: app-spec                # a registered intake that drafts the job input from the text
  delivery: choose                # or `fixed` when the workflow delivers to its own target
vars: {key: value}                # constants, read as ${vars.key}
source: {use: <source>, with: {...}}       # where the jobs come from
executor: {use: local}                      # optional
providers:                                  # only the ones the steps need
  scm: {use: <scm>, with: {...}}
  llm: {use: <llm>, with: {...}}
steps:
  - id: unique_id
    use: <step name from the list below>
    with: {param: value}          # exactly the parameters listed for that step
    when: "steps.build.status == 'failed'"      # optional condition
    on_fail: fail                 # fail | discard (stop, change nothing) | continue
    blocking: true                # false: a failure only becomes a note
```

Rules the validator enforces:
- `use:` must name a registered step; `with:` keys must be that step's parameters; required ones must be present.
- A step that lists `needs: [scm]` or `[llm]` requires that provider under `providers:`.
- Step ids are unique, and `${steps.<id>...}` / `steps.<id>` may only refer to steps that run EARLIER.
- Templates: `${job.<attr>}`, `${steps.<id>.outputs.<key>}`, `${steps.<id>.status}`, `${vars.<k>}`, `${env.python}`.
- `when` is a tiny expression language: names, attribute access, literals, comparisons, `in`, `and`/`or`/`not`.
  No function calls, no indexing, no arithmetic. Loops do not exist.
- Do not invent steps, providers or parameters. If the goal needs something that is not listed, say so.
"""


def _requirement(p: dict[str, Any]) -> str:
    if p["required"]:
        return " (required)"
    return f" (default {p['default']!r})" if "default" in p else " (optional)"


def _params_line(params: list[dict[str, Any]], with_types: bool) -> str:
    labels = [(f"{p['name']}: {p['type']}" if with_types else p["name"]) + _requirement(p) for p in params]
    return "; ".join(labels) or "none"


def render_markdown() -> str:
    d = describe()
    lines = [FORMAT_GUIDE, "# Steps (the only values allowed for `use:` in `steps`)", ""]
    for name, info in d["steps"].items():
        needs = f" [needs providers: {', '.join(info['needs'])}]" if info["needs"] else ""
        lines += [f"## {name}{needs}", info["doc"] or "(no description)",
                  f"params: {_params_line(info['params'], True)}", ""]
    lines += ["# Plugins for `source`, `executor` and `providers` (`use:` + `with:` = constructor arguments)", ""]
    for kind in ("source", "executor", "scm", "llm", "secrets"):
        for name, info in d[kind].items():
            lines += [f"## {kind}: {name}", info["doc"] or "(no description)",
                      f"with: {_params_line(info['params'], False)}", ""]
    lines += ["# Intakes (for `route.intake`)", ""]
    lines += [f"- {name}: {info['doc']}" for name, info in d["intake"].items()]
    return "\n".join(lines) + "\n"
