#!/usr/bin/env python3
"""Apply the YAML title to a Herdr pane so the sidebar shows the full name."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from load_config import agent_name, display_agent, pane_label, resolve


def herdr(args: list[str]) -> None:
    proc = subprocess.run(["herdr", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr or proc.stdout)
        raise SystemExit(proc.returncode or 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="")
    parser.add_argument("--seat", required=True)
    parser.add_argument("--pane", required=True)
    parser.add_argument("--n", type=int, default=1)
    args = parser.parse_args()
    project = Path(args.project) if args.project else None
    config = resolve(project)
    if args.seat not in config.get("roles", {}):
        print(f"error: unknown seat {args.seat}", file=sys.stderr)
        return 2
    label = pane_label(config, args.seat, args.n)
    shown = display_agent(config, args.seat, args.n)
    vis = config.get("visibility") or {}
    source = vis.get("metadata_source") or "workflow-herdr"
    herdr(["pane", "rename", args.pane, label])
    herdr(
        [
            "pane",
            "report-metadata",
            args.pane,
            "--source",
            source,
            "--display-agent",
            shown,
            "--title",
            label,
        ]
    )
    json.dump(
        {
            "pane_id": args.pane,
            "agent_name": agent_name(config, args.seat, args.n),
            "pane_label": label,
            "display_agent": shown,
        },
        sys.stdout,
        indent=2,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
