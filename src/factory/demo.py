"""Creates a sandbox for the demo: bare git 'remotes', a catalog (the Neptune stand-in)
and an empty PR folder. Six toy microservices, each exercising a different path."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from factory.plugins.builtin.util import git

CHECK_PY = '''\
import sys

cfg = {}
for line in open("build.cfg"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        key, value = line.split("=", 1)
        cfg[key.strip()] = value.strip()

java = int(cfg.get("java_version", "0"))
errors = []
if cfg.get("broken_baseline") == "true":
    errors.append("error: compile failure in module core")
if java >= 17 and "legacy_flag" in cfg:
    errors.append("error: unsupported option 'legacy_flag' for java 17+")
if java >= 17 and "native_dep" in cfg:
    errors.append("error: dependency 'native_dep' has no build for java 17+")
if "--coverage" in sys.argv and int(cfg.get("coverage_pct", "0")) < 80:
    errors.append(f"coverage {cfg.get('coverage_pct')}% is below 80%")

if errors:
    print("\\n".join(errors))
    sys.exit(1)
print("BUILD OK")
'''

# name, java_version, architecture, extra build.cfg keys, what should happen
REPOS = [
    ("svc-clean-ok", 11, "clean", {"coverage_pct": 85}),                      # scaffold path, green
    ("svc-other-ok", 8, "other", {"coverage_pct": 40}),                       # LLM path + low coverage note
    ("svc-needs-repair", 11, "clean", {"legacy_flag": "true", "coverage_pct": 90}),  # build breaks, LLM repairs
    ("svc-broken-baseline", 11, "clean", {"broken_baseline": "true", "coverage_pct": 90}),  # discarded
    ("svc-unfixable", 11, "clean", {"native_dep": "libfoo", "coverage_pct": 90}),  # repair gives up
    ("svc-modern", 21, "clean", {"coverage_pct": 95}),                        # already up to date
]


def demo_init(dest: str | Path = "demo") -> Path:
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    (dest / "remote").mkdir(parents=True)
    (dest / "prs").mkdir()
    catalog = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, java, arch, extra in REPOS:
            work = Path(tmp) / name
            work.mkdir()
            cfg = [f"java_version={java}", f"architecture={arch}"]
            cfg += [f"{k}={v}" for k, v in extra.items()]
            (work / "build.cfg").write_text("\n".join(cfg) + "\n")
            (work / "check.py").write_text(CHECK_PY)
            git("init", "--quiet", "-b", "main", cwd=work)
            git("add", "-A", cwd=work)
            git("-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "initial", cwd=work)
            git("clone", "--quiet", "--bare", str(work), str(dest / "remote" / f"{name}.git"))
            catalog.append({"name": name, "java_version": java, "architecture": arch})
    (dest / "catalog.json").write_text(json.dumps(catalog, indent=2))
    return dest
