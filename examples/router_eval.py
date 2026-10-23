"""Measure a router on labelled requests, to choose `--threshold` from data instead of by feel.

    python examples/router_eval.py                       # jev (needs TYPESAFE_API_KEY) on the packaged templates
    python examples/router_eval.py --router keyword      # offline sanity run of the script itself
    python examples/router_eval.py --cases mine.yaml --workflows-dir workflows

It prints one line per request (what was wanted, what was chosen, how sure) and then, for each threshold, how many
requests would have run correctly, run WRONG (the number that matters: it should be 0), or stopped to ask.
One router call per request; nothing else is contacted and nothing is run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from minifactory import ask as routing
from minifactory import templates
from minifactory.core import registry
from minifactory.core.workflow import load_workflow

THRESHOLDS = (0.5, 0.6, 0.7, 0.8, 0.9)


def routable_templates() -> dict[str, routing.Routable]:
    found = {}
    for path in sorted((Path(templates.__file__).parent / "templates").glob("*/workflow.yaml")):
        spec = load_workflow(path)
        if spec.route:
            found[spec.name] = routing.Routable(path, spec)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--router", default="jev")
    parser.add_argument("--cases", default=str(Path(__file__).with_name("router_eval.yaml")))
    parser.add_argument("--workflows-dir", help="use your workflows instead of the packaged templates")
    args = parser.parse_args()
    registry.load_plugins()
    candidates = routing.discover(args.workflows_dir) if args.workflows_dir else routable_templates()
    router = registry.get("router", args.router)()
    rows = []
    for case in yaml.safe_load(Path(args.cases).read_text()):
        d = router.choose(case["say"], [r.candidate for r in candidates.values()])
        ranking = routing.ranked(d)
        margin = ranking[0][1] - ranking[1][1] if len(ranking) > 1 else ranking[0][1]
        rows.append((case["say"], case["want"], d.choice or "none", d.confidence, margin, d.actionable))
        mark = "ok " if (d.choice or "none") == case["want"] else "BAD"
        print(f"{mark} {case['say'][:58]:<58} want {case['want']:<16} got {(d.choice or 'none'):<16} "
              f"p={d.confidence:.2f} margin={margin:.2f}")
    print(f"\n{'threshold':>9} {'runs ok':>8} {'runs WRONG':>11} {'asks':>6}   (of {len(rows)})")
    for t in THRESHOLDS:
        acts = [(want == got) for _, want, got, conf, _, _ in rows if conf >= t and got != "none"]
        asks = sum(1 for _, _, got, conf, _, _ in rows if conf < t and got != "none")
        print(f"{t:>9} {sum(acts):>8} {len(acts) - sum(acts):>11} {asks:>6}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
