#!/usr/bin/env python3
"""Rename pane, tab, and workspace so the sidebar shows the seat, not Brain."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from herdr_cli import HerdrError, herdr
from load_config import (
    agent_name,
    display_agent,
    pane_label,
    resolve,
    tab_label,
    workspace_label,
)
from run_store import load_identity


def label_seat(
    *,
    project: Path,
    change: str,
    seat: str,
    pane_id: str,
    number: int = 1,
    stream: str = "",
    tab_id: str = "",
    workspace_id: str = "",
    runner=None,
    config: dict | None = None,
) -> dict:
    config = config or resolve(project)
    nodes = config.get("nodes") or config.get("roles") or {}
    if seat not in nodes:
        raise HerdrError(f"unknown seat {seat}", "unknown_seat")
    identity = load_identity(project, change, config)
    session = identity.get("herdr_session")
    machine = identity.get("machine")
    vis = config.get("visibility") or {}
    source = vis.get("metadata_source") or "workflow-herdr"
    pane = pane_label(config, seat, number, change)
    shown = display_agent(config, seat, number, change)
    herdr(
        ["pane", "rename", pane_id, pane],
        session=session,
        machine=machine,
        runner=runner,
    )
    herdr(
        [
            "pane",
            "report-metadata",
            pane_id,
            "--source",
            source,
            "--display-agent",
            shown,
            "--title",
            pane,
        ],
        session=session,
        machine=machine,
        runner=runner,
    )
    tab_id = tab_id or identity.get("tab_id") or ""
    tab_name = ""
    if tab_id:
        tab_name = tab_label(config, change=change, stream=stream)
        herdr(
            ["tab", "rename", tab_id, tab_name],
            session=session,
            machine=machine,
            runner=runner,
        )
    workspace_id = workspace_id or identity.get("workspace_id") or ""
    workspace_name = ""
    if workspace_id and stream:
        workspace_name = workspace_label(
            config,
            repo=identity.get("repo") or project.name,
            change=change,
            stream=stream,
        )
        herdr(
            ["workspace", "rename", workspace_id, workspace_name],
            session=session,
            machine=machine,
            runner=runner,
        )
    return {
        "pane_id": pane_id,
        "agent_name": agent_name(config, seat, number, change),
        "pane_label": pane,
        "display_agent": shown,
        "tab_id": tab_id or None,
        "tab_label": tab_name or None,
        "workspace_id": workspace_id or None,
        "workspace_label": workspace_name or None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--change", required=True)
    parser.add_argument("--seat", required=True)
    parser.add_argument("--pane", required=True)
    parser.add_argument("--n", type=int, default=1)
    parser.add_argument("--stream", default="")
    args = parser.parse_args()
    project = Path(args.project).resolve()
    try:
        result = label_seat(
            project=project,
            change=args.change,
            seat=args.seat,
            pane_id=args.pane,
            number=args.n,
            stream=args.stream,
        )
    except HerdrError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
