#!/usr/bin/env python3
"""Create the graph's Herdr layout in one shot. Rollback panes if start fails."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from herdr_cli import HerdrError, herdr, value_for
from label_seat import label_seat
from load_config import graph_of, node_of, resolve, tab_label
from record_pane import record_pane
from run_store import load_identity, paths_for, save_identity
from start_seat import start_seat
from worktree_seat import ensure_worktree, rollback_worktree
from yaml_lite import load_yaml


def _pane_id(payload: dict) -> str:
    result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    pane = result.get("pane") if isinstance(result.get("pane"), dict) else result
    pane_id = value_for(pane, "pane_id")
    if not pane_id:
        raise HerdrError("pane split returned no pane_id", "bad_json", payload)
    return str(pane_id)


def layout_seats_for(graph: dict) -> list[str]:
    layout = graph.get("layout") if isinstance(graph.get("layout"), dict) else {}
    seats = list(layout.get("seats") or [])
    if seats:
        return [seat for seat in seats if seat != "brain"]
    return [seat for seat in (graph.get("nodes") or []) if seat != "brain"]


def _shared_seat(config: dict, seat: str) -> bool:
    instances = node_of(config, seat).get("instances")
    return instances in (None, 1, "1")


def uses_worktree_pairs(graph: dict, config: dict, volume: str) -> bool:
    parallel = config.get("parallel") or {}
    only = parallel.get("only_volume")
    if only and only != volume:
        return False
    layout = graph.get("layout") if isinstance(graph.get("layout"), dict) else {}
    return bool(
        graph.get("worktrees")
        or graph.get("parallel")
        or layout.get("workspace") == "worktree"
        or parallel.get("each_workstream_own_worktree")
    )


def layout_streams(
    identity: dict, *, project: Path, change: str, config: dict, graph: dict
) -> list[str]:
    raw = identity.get("streams")
    if isinstance(raw, str) and raw.strip():
        ids = [raw.strip()]
    elif isinstance(raw, list):
        ids = [str(item).strip() for item in raw if str(item).strip()]
    else:
        ids = []
    if not ids:
        state_path = paths_for(project, change, config).get("state")
        if state_path and Path(state_path).is_file():
            tasks = load_yaml(Path(state_path).read_text(encoding="utf-8")) or {}
            for item in tasks.get("workstreams") or []:
                if isinstance(item, dict) and item.get("id"):
                    ids.append(str(item["id"]))
    if uses_worktree_pairs(graph, config, identity.get("volume") or identity.get("graph") or ""):
        minimum = int((config.get("guards") or {}).get("large_min_runnable_tasks") or 2)
        if len(ids) < minimum:
            raise HerdrError(
                f"large needs at least {minimum} streams in identity.streams or tasks.workstreams",
                "missing_streams",
            )
    return ids


def layout_graph(
    *,
    project: Path,
    change: str,
    volume: str | None = None,
    current_pane: str = "",
    runner=None,
    config: dict | None = None,
    sleep=None,
) -> dict:
    config = config or resolve(project)
    identity = load_identity(project, change, config)
    volume = volume or identity.get("volume") or identity.get("graph")
    graph = graph_of(config, volume)
    if not graph:
        raise HerdrError(f"unknown graph {volume}", "unknown_graph")
    seats = layout_seats_for(graph)
    if not seats:
        raise HerdrError(f"{volume} has no layout seats", "no_layout")
    session = identity.get("herdr_session")
    machine = identity.get("machine")
    sleep_fn = sleep if sleep is not None else time.sleep
    current_pane = current_pane or os.environ.get("HERDR_PANE_ID") or ""
    if not current_pane:
        payload = herdr(
            ["pane", "current", "--current"],
            session=session,
            machine=machine,
            runner=runner,
        )
        current_pane = str(
            value_for(payload.get("result") or payload, "pane_id") or ""
        )
    if not current_pane:
        raise HerdrError("need HERDR_PANE_ID or pane current", "missing_pane")

    created_panes: list[str] = []
    created_workspaces: list[str] = []
    started: list[dict] = []
    files = paths_for(project, change, config)
    session_file = files["session"]
    layout = graph.get("layout") if isinstance(graph.get("layout"), dict) else {}
    fan_out = uses_worktree_pairs(graph, config, volume)

    def start_one(
        *,
        seat: str,
        number: int,
        parent: str,
        direction: str,
        cwd: str,
        stream: str = "",
        tab_id: str = "",
        workspace_id: str = "",
    ) -> str:
        payload = herdr(
            [
                "pane",
                "split",
                "--pane",
                parent,
                "--direction",
                direction,
                "--cwd",
                cwd,
                "--no-focus",
            ],
            session=session,
            machine=machine,
            runner=runner,
        )
        pane_id = _pane_id(payload)
        created_panes.append(pane_id)
        record_pane(
            session_file,
            config=config,
            pane_id=pane_id,
            seat=seat,
            number=number,
            status="created",
            change=change,
            tab_id=tab_id or identity.get("tab_id") or "",
        )
        result = start_seat(
            project=project,
            change=change,
            seat=seat,
            number=number,
            pane_id=pane_id,
            runner=runner,
            sleep=sleep_fn,
            config=config,
        )
        record_pane(
            session_file,
            config=config,
            pane_id=pane_id,
            seat=seat,
            number=number,
            status="running",
            change=change,
            tab_id=tab_id or identity.get("tab_id") or "",
        )
        label_seat(
            project=project,
            change=change,
            seat=seat,
            pane_id=pane_id,
            number=number,
            stream=stream,
            tab_id=tab_id,
            workspace_id=workspace_id,
            runner=runner,
            config=config,
        )
        started.append({**result, "stream": stream, "number": number})
        return pane_id

    try:
        if fan_out:
            streams = layout_streams(
                identity, project=project, change=change, config=config, graph=graph
            )
            shared = [seat for seat in seats if _shared_seat(config, seat)]
            paired = [seat for seat in seats if not _shared_seat(config, seat)]
            if "dispatcher" in paired and "worker" in paired:
                dispatcher_first = ["dispatcher", "worker"]
                paired = [seat for seat in dispatcher_first if seat in paired] + [
                    seat for seat in paired if seat not in dispatcher_first
                ]
            parent = current_pane
            for index, seat in enumerate(shared):
                parent = start_one(
                    seat=seat,
                    number=1,
                    parent=current_pane if index == 0 else parent,
                    direction="right" if index == 0 else "down",
                    cwd=str(project),
                )
            for offset, stream in enumerate(streams, start=1):
                wt = ensure_worktree(
                    project=project,
                    change=change,
                    stream=str(stream),
                    branch=f"{change}/{stream}",
                    runner=runner,
                    config=config,
                )
                if wt.get("action") == "created" and wt.get("workspace_id"):
                    created_workspaces.append(wt["workspace_id"])
                pair_parent = wt.get("pane_id") or current_pane
                pair_cwd = wt.get("cwd") or str(project)
                pair_tab = wt.get("tab_id") or ""
                pair_ws = wt.get("workspace_id") or ""
                last = pair_parent
                for index, seat in enumerate(paired):
                    last = start_one(
                        seat=seat,
                        number=offset,
                        parent=pair_parent if index == 0 else last,
                        direction="right" if index == 0 else "down",
                        cwd=str(pair_cwd),
                        stream=str(stream),
                        tab_id=pair_tab,
                        workspace_id=pair_ws,
                    )
        else:
            parent = current_pane
            for index, seat in enumerate(seats):
                parent = start_one(
                    seat=seat,
                    number=1,
                    parent=current_pane if index == 0 else parent,
                    direction="right" if index == 0 else "down",
                    cwd=str(project),
                )
        if layout.get("tab") == "rename" or layout.get("tab") is None:
            tab_id = identity.get("tab_id") or os.environ.get("HERDR_TAB_ID") or ""
            if tab_id:
                herdr(
                    ["tab", "rename", tab_id, tab_label(config, change=change)],
                    session=session,
                    machine=machine,
                    runner=runner,
                )
                if not identity.get("tab_id"):
                    identity["tab_id"] = tab_id
                    save_identity(project, change, identity, config)
    except Exception:
        for pane_id in reversed(created_panes):
            if any(
                item.get("pane_id") == pane_id
                and item.get("action") in ("started", "focused")
                for item in started
            ):
                continue
            try:
                herdr(
                    ["pane", "close", pane_id],
                    session=session,
                    machine=machine,
                    runner=runner,
                )
            except HerdrError:
                pass
        for workspace_id in reversed(created_workspaces):
            try:
                rollback_worktree(
                    project=project,
                    change=change,
                    workspace_id=workspace_id,
                    runner=runner,
                    config=config,
                )
            except HerdrError:
                pass
        raise
    return {
        "ok": True,
        "volume": volume,
        "seats": started,
        "panes": created_panes,
        "workspaces": created_workspaces,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--change", required=True)
    parser.add_argument("--volume", default="")
    parser.add_argument("--pane", default="")
    args = parser.parse_args()
    project = Path(args.project).resolve()
    try:
        result = layout_graph(
            project=project,
            change=args.change,
            volume=args.volume or None,
            current_pane=args.pane,
        )
    except HerdrError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
