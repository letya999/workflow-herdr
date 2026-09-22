#!/usr/bin/env python3
"""Record a run-owned pane before starting or controlling its agent."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from load_config import agent_name, expand_layout, resolve
from yaml_lite import dump_yaml, load_yaml

STATUSES = ("created", "running", "failed")
ROLE_KEYS = {
    "orchestrator": "orchestrator",
    "dispatcher": "dispatchers",
    "worker": "workers",
}


def _workspace_of(pane_id: str) -> str:
    workspace_id, separator, rest = pane_id.partition(":p")
    if not separator or not rest:
        raise ValueError(f"invalid pane id: {pane_id}")
    return workspace_id


def _tab_of(pane_id: str, tab_id: str) -> str:
    if tab_id:
        return tab_id
    workspace_id = _workspace_of(pane_id)
    return f"{workspace_id}:t1"


def record_pane(
    session_file: Path,
    *,
    config: dict | None = None,
    pane_id: str,
    seat: str,
    number: int,
    status: str,
    error: str = "",
    change: str = "",
    tab_id: str = "",
    previous_pane_id: str = "",
) -> dict:
    session = json.loads(session_file.read_text(encoding="utf-8"))
    workspace_id = _workspace_of(pane_id)
    recorded_workspace = session.get("workspace_id")
    created = session.setdefault("created", {})
    known = set()
    if recorded_workspace:
        known.add(recorded_workspace)
    for item in created.get("workspaces") or []:
        if isinstance(item, str) and item:
            known.add(item)
        elif isinstance(item, dict) and item.get("workspace_id"):
            known.add(item["workspace_id"])
    if recorded_workspace and recorded_workspace != workspace_id:
        if workspace_id not in known and not previous_pane_id:
            raise ValueError(
                f"pane {pane_id} belongs to {workspace_id}, not {recorded_workspace}"
            )
        if previous_pane_id and workspace_id not in known:
            created.setdefault("workspaces", []).append({"workspace_id": workspace_id})
    if not session.get("workspace_id"):
        session["workspace_id"] = workspace_id
    resolved = config or resolve(None)
    change = change or session.get("change") or ""
    name = agent_name(resolved, seat, number, change)
    panes = session.setdefault("created", {}).setdefault("panes", [])
    pane = next((item for item in panes if item.get("pane_id") == pane_id), None)
    if pane is None and previous_pane_id:
        pane = next(
            (item for item in panes if item.get("pane_id") == previous_pane_id), None
        )
        if pane is not None:
            pane["previous_pane_id"] = previous_pane_id
    if pane is None and name:
        pane = next((item for item in panes if item.get("agent") == name), None)
        if pane is not None and pane.get("pane_id") != pane_id:
            pane["previous_pane_id"] = pane.get("pane_id")
    if pane is None:
        pane = {"pane_id": pane_id}
        panes.append(pane)
    pane.update(
        {
            "pane_id": pane_id,
            "seat": seat,
            "number": number,
            "status": status,
            "tab_id": _tab_of(pane_id, tab_id or pane.get("tab_id") or ""),
            "agent": name,
        }
    )
    pane.pop("error", None)
    if error:
        pane["error"] = error

    binding = {
        "pane_id": pane_id,
        "tab_id": pane["tab_id"],
        "workspace_id": workspace_id,
        "agent": name,
        "status": status,
        "number": number,
    }
    nodes = session.setdefault("nodes", {})
    many = bool((resolved.get("nodes") or {}).get(seat, {}).get("many"))
    if seat == "orchestrator" or not many:
        nodes[seat] = {**(nodes.get(seat) or {}), **binding}
    else:
        entries = nodes.setdefault(seat, [])
        if not isinstance(entries, list):
            entries = [entries]
            nodes[seat] = entries
        existing = next((item for item in entries if item.get("agent") == name), None)
        if existing is None:
            entries.append(binding)
        else:
            existing.update(binding)

    role = {"pane_id": pane_id, "agent": name, "tab_id": pane["tab_id"]}
    role_key = ROLE_KEYS.get(seat)
    if role_key:
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
    _sync_identity(
        session_file.parent / "identity.yaml",
        workspace_id=workspace_id,
        tab_id=pane.get("tab_id") or "",
    )
    return pane


def _sync_identity(path: Path, *, workspace_id: str, tab_id: str) -> None:
    if not path.is_file():
        return
    data = load_yaml(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return
    changed = False
    if workspace_id and not data.get("workspace_id"):
        data["workspace_id"] = workspace_id
        changed = True
    if tab_id and not data.get("tab_id"):
        data["tab_id"] = tab_id
        changed = True
    if changed:
        path.write_text(dump_yaml(data), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--change", required=True)
    parser.add_argument("--seat", required=True)
    parser.add_argument("--pane", required=True)
    parser.add_argument("--n", type=int, default=1)
    parser.add_argument("--status", required=True, choices=STATUSES)
    parser.add_argument("--error", default="")
    parser.add_argument("--tab", default="")
    parser.add_argument("--previous-pane", default="")
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
            change=args.change,
            tab_id=args.tab,
            previous_pane_id=args.previous_pane,
        )
    except (KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    json.dump(pane, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
