"""Generate `site/src/content/docs/reference/catalog.md` directly from the minifactory registry,
stack profiles and role profiles, so the documentation reference is never stale."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from minifactory import catalog, roles, stacks  # noqa: E402
from minifactory.core import registry  # noqa: E402

TARGET = ROOT / "site" / "src" / "content" / "docs" / "reference" / "catalog.md"


def _fmt_default(p: dict[str, object]) -> str:
    if p.get("required"):
        return "**required**"
    if "default" in p:
        return f"`{p['default']!r}`"
    return "_optional_"


def build_markdown() -> str:
    registry.load_plugins()
    info = catalog.describe()
    lines = [
        "---",
        "title: Steps & Plugins Catalog",
        "description: Auto-generated reference of all built-in steps, providers, intakes, stacks, and roles.",
        "---",
        "",
        ":::note[Auto-generated from code]",
        "This page is generated directly from `minifactory.catalog.describe()`, `minifactory.stacks.available()`,",
        "and `minifactory.roles.available()`. Run `minifactory plugins --schema` in your terminal to see this",
        "including any custom workspace stacks, roles, or third-party plugins.",
        ":::",
        "",
        "## Steps (`steps:` -> `use:`)",
        "",
    ]
    for name, step in info["steps"].items():
        needs = f" — requires `{', '.join(step['needs'])}`" if step["needs"] else ""
        lines += [f"### `{name}`{needs}", "", step["doc"] or "_No description._", ""]
        params = step["params"]
        if params:
            lines += ["| Parameter | Type | Requirement / Default |", "|---|---|---|"]
            for p in params:
                lines.append(f"| `{p['name']}` | `{p['type']}` | {_fmt_default(p)} |")
            lines.append("")
        else:
            lines += ["_No parameters._", ""]

    lines += ["## Packaged Roles (`role:` on `agent.*` steps)", ""]
    lines += ["| Role | Description | Boundaries |", "|---|---|---|"]
    for name, r in roles.available(ROOT).items():
        bounds = []
        if r.allowed_prefixes:
            bounds.append(f"allowed: `{', '.join(r.allowed_prefixes)}`")
        if r.forbid_prefixes:
            bounds.append(f"forbid: `{', '.join(r.forbid_prefixes)}`")
        if r.tests_only:
            bounds.append("`tests_only: true`")
        lines.append(f"| `{name}` | {r.description} | {'; '.join(bounds) or 'none'} |")
    lines.append("")

    lines += ["## Packaged Stacks (`stack:` / `${job.stack}`)", ""]
    lines += ["| Stack | Description | Required Tools | Auto-detect Files |", "|---|---|---|---|"]
    for name, s in stacks.available(ROOT).items():
        req = ", ".join(f"`{t}`" for t in s.requires) or "none"
        det = ", ".join(f"`{d}`" for d in s.detect) or "_pinned only_"
        lines.append(f"| `{name}` | {s.description} | {req} | {det} |")
    lines.append("")

    lines += ["## Providers, Sources & Executors", ""]
    for kind in ("scm", "llm", "secrets", "source", "executor"):
        lines += [f"### `{kind}` plugins", ""]
        for name, plug in info[kind].items():
            lines += [f"#### `{kind}: {name}`", "", plug["doc"] or "_No description._", ""]
            if plug["params"]:
                params_str = ", ".join(f"`{p['name']}` ({_fmt_default(p)})" for p in plug["params"])
                lines += [f"**`with:` parameters:** {params_str}", ""]

    lines += ["## Intakes (`route.intake`)", ""]
    for name, intake in info["intake"].items():
        lines.append(f"- **`{name}`**: {intake['doc']}")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(build_markdown(), encoding="utf-8")
    print(f"wrote {TARGET.relative_to(ROOT)}")
