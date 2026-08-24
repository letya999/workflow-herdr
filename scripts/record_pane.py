#!/usr/bin/env python3
"""Record a run-owned pane before starting or controlling its agent."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from load_config import agent_name, expand_layout, resolve


STATUSES = ("created", "running", "failed")
ROLE_KEYS = {
    "orchestrator": "orchestrator",
    "dispatcher": "dispatchers",
    "worker": "workers",
}


def record_pane(
    session_file: Path,
    *,
    config: dict | None = None,
    pane_id: str,
    seat: str,
    number: int,
    status: str,
    error: str = "",
) -> dict:
    session = json.loads(session_file.read_text(encoding="utf-8"))
    workspace_id, separator, _ = pane_id.partition(":p")
    if not separator:
        raise ValueError(f"invalid pane id: {pane_id}")
    recorded_workspace = session.get("workspace_id")
    if recorded_workspace and recorded_workspace != workspace_id:
        raise ValueError(
            f"pane {pane_id} belongs to {workspace_id}, not {recorded_workspace}"
        )
    session["workspace_id"] = workspace_id
    panes = session.setdefault("created", {}).setdefault("panes", [])
    pane = next((item for item in panes if item.get("pane_id") == pane_id), None)
    if pane is None:
        pane = {"pane_id": pane_id}
        panes.append(pane)
    pane.update({"seat": seat, "number": number, "status": status})
    pane.pop("error", None)
    if error:
        pane["error"] = error

    role = {
        "pane_id": pane_id,
        "agent": agent_name(config or resolve(None), seat, number),
    }
    role_key = ROLE_KEYS[seat]
    roles = session.setdefault("roles", {})
    if role_key == "orchestrator":
        roles[role_key] = {**(roles.get(role_key) or {}), **role}
    else:
        entries = roles.setdefault(role_key, [])
        existing = next(
            (item for item in entries if item.get("agent") == role["agent"]), None
        )
        if existing is None:
            entries.append(role)
        else:
            existing.update(role)

    temporary = session_file.with_suffix(".tmp")
    temporary.write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")
    temporary.replace(session_file)
    return pane


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--change", required=True)
    parser.add_argument("--seat", required=True, choices=tuple(ROLE_KEYS))
    parser.add_argument("--pane", required=True)
    parser.add_argument("--n", type=int, default=1)
    parser.add_argument("--status", required=True, choices=STATUSES)
    parser.add_argument("--error", default="")
    args = parser.parse_args()

    project = Path(args.project).resolve()
    config = resolve(project)
    session_file = project / expand_layout(config, change=args.change)["session"]
    if not session_file.is_file():
        print(f"error: missing run file: {session_file}", file=sys.stderr)
        return 2
    try:
        pane = record_pane(
            session_file,
            config=config,
            pane_id=args.pane,
            seat=args.seat,
            number=args.n,
            status=args.status,
            error=args.error,
        )
    except (KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    json.dump(pane, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
