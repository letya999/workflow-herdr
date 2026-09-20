#!/usr/bin/env python3
"""Start gate: doctor the resolved workflow, then collect detection candidates."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from detect import detect, write_draft
from workflow_guard import doctor


def bootstrap(
    project: Path,
    *,
    volume: str = "",
    change: str = "",
    env=None,
    runner=None,
    inventories=None,
    kinds=None,
    protocol=None,
) -> dict:
    health = doctor(
        project,
        change,
        volume=volume,
        env=env,
        runner=runner,
        live=True,
        inventories=inventories,
        kinds=kinds,
        protocol=protocol,
    )
    drafted = write_draft(project)
    found = detect(project)
    errors = list(health.get("errors") or [])
    if not health.get("ok"):
        next_step = "fix doctor errors; do not split panes"
    elif found.get("gaps"):
        next_step = (
            "Brain confirms .herdr/detection.yaml draft and fills sizing_graph"
        )
    else:
        next_step = (
            f"init_work + layout_graph for {found.get('classified', {}).get('sizing_graph')}"
        )
    fixes = [
        seat.get("fix")
        for seat in (health.get("seats") or {}).values()
        if isinstance(seat, dict) and seat.get("fix")
    ]
    proto_fix = (health.get("protocol") or {}).get("fix")
    if proto_fix:
        fixes.append(proto_fix)
    return {
        "ok": bool(health.get("ok")),
        "doctor": health,
        "detect": {
            "ok": found.get("ok"),
            "gaps": found.get("gaps"),
            "groups": {
                name: {"hits": group.get("hits"), "files": group.get("files")}
                for name, group in (found.get("groups") or {}).items()
            },
            "brain_task": found.get("brain_task"),
            "classified": found.get("classified"),
            "next": found.get("next"),
            "draft": drafted,
        },
        "errors": errors,
        "fixes": fixes,
        "next": next_step,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--volume", default="")
    parser.add_argument("--change", default="")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Ignore probe-cache and re-run live CLI inventories",
    )
    args = parser.parse_args()
    if args.fresh:
        os.environ["WORKFLOW_HERDR_PROBE_FRESH"] = "1"
    result = bootstrap(
        Path(args.project).resolve(), volume=args.volume, change=args.change
    )
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
