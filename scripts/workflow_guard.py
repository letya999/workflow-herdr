#!/usr/bin/env python3
"""Fail-fast checks before and during a workflow-herdr run."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from load_config import expand_layout, resolve
from yaml_lite import load_yaml


WINDOWS_EXECUTABLE_SUFFIXES = (".exe", ".com", ".cmd", ".bat")
RUNNABLE_STATES = {"ready", "assigned", "running", "in_review", "rejected"}
ASSIGNED_STATES = {"assigned", "running", "in_review", "rejected", "accepted"}


def resolve_command(command: str) -> str | None:
    """Resolve a command to a Windows-runnable file, avoiding npm POSIX shims."""
    path = Path(command)
    if path.parent != Path("."):
        return str(path.resolve()) if path.is_file() else None
    if os.name != "nt":
        return shutil.which(command)
    suffix = path.suffix.lower()
    if suffix:
        found = shutil.which(command)
        return (
            str(Path(found).resolve())
            if found and suffix in WINDOWS_EXECUTABLE_SUFFIXES
            else None
        )
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        root = Path(directory)
        for executable_suffix in WINDOWS_EXECUTABLE_SUFFIXES:
            candidate = root / f"{command}{executable_suffix}"
            if candidate.is_file():
                return str(candidate.resolve())
    return None


def launch_command(executable: str, args: list[str]) -> str:
    """Build the exact shell command that Herdr should send to a pane."""
    if os.name == "nt":
        quoted = (f"'{value.replace("'", "''")}'" for value in [executable, *args])
        return f"& {' '.join(quoted)}"
    return shlex.join([executable, *args])


def preflight(project: Path, volume: str) -> dict:
    config = resolve(project)
    recipe = (config.get("volumes") or {}).get(volume)
    errors: list[str] = []
    seats: dict[str, dict] = {}
    if not recipe:
        return {"ok": False, "errors": [f"unknown volume: {volume}"], "seats": seats}
    if os.environ.get("HERDR_ENV") != "1":
        errors.append("HERDR_ENV must be 1")
    if not resolve_command("herdr"):
        errors.append("herdr is not executable")
    for seat in recipe.get("seats") or []:
        role = (config.get("roles") or {}).get(seat) or {}
        cli_name = role.get("cli")
        if not role.get("start", True) or cli_name == "human":
            continue
        resolved = resolve_command(str(cli_name))
        cli = (config.get("clis") or {}).get(cli_name) or {}
        values = {"model": role.get("model"), "effort": role.get("effort")}
        args = [str(arg).format_map(values) for arg in cli.get("native_args") or []]
        seats[seat] = {
            "command": cli_name,
            "resolved": resolved,
            "launch": launch_command(resolved, args) if resolved else None,
        }
        if not resolved:
            errors.append(f"{seat}: no safe executable for {cli_name}")
    return {"ok": not errors, "errors": errors, "seats": seats}


def validate(project: Path, change: str) -> dict:
    config = resolve(project)
    paths = expand_layout(config, change=change)
    state_file = project / paths["state"]
    session_file = project / paths["session"]
    state = load_yaml(state_file.read_text(encoding="utf-8")) or {}
    session = json.loads(session_file.read_text(encoding="utf-8"))
    errors: list[str] = []
    volume = session.get("volume") or state.get("volume")
    recipe = (config.get("volumes") or {}).get(volume) or {}
    tasks = state.get("tasks") or []
    legal_states = set((config.get("task_states") or {}).keys())
    runnable = [task for task in tasks if task.get("state") in RUNNABLE_STATES]
    workstreams = state.get("workstreams") or []
    created = session.get("created") or {}
    created_workspaces = created.get("workspaces") or []
    created_tabs = created.get("tabs") or []
    roles = session.get("roles") or {}
    if volume not in (config.get("volumes") or {}):
        errors.append(f"unknown volume: {volume}")
    if volume == "large":
        if workstreams and len(workstreams) < 2:
            errors.append("large requires at least two workstreams")
        elif not workstreams and len(runnable) < 2:
            errors.append("large requires at least two runnable tasks")
    if volume == "medium" and (created_workspaces or created_tabs):
        errors.append("medium must stay in the current workspace and tab")
    if recipe.get("worktrees") is False and (workstreams or created_workspaces):
        if any(stream.get("worktree") for stream in workstreams) or created_workspaces:
            errors.append(f"{volume} forbids worktrees/worktree workspaces")
    task_ids = [task.get("id") for task in tasks]
    if None in task_ids or len(task_ids) != len(set(task_ids)):
        errors.append("tasks require unique non-empty ids")
    stream_ids = [stream.get("id") for stream in workstreams]
    if None in stream_ids or len(stream_ids) != len(set(stream_ids)):
        errors.append("workstreams require unique non-empty ids")
    for task in tasks:
        task_id = task.get("id", "<unknown>")
        task_state = task.get("state")
        stream = next(
            (
                item
                for item in workstreams
                if item.get("task") == task_id or item.get("id") == task_id
            ),
            None,
        )
        if task_state not in legal_states:
            errors.append(f"{task_id}: unknown state {task_state}")
        if task_state in ASSIGNED_STATES and not stream:
            errors.append(f"{task_id}: {task_state} requires a workstream assignment")
        if stream and task_state in ASSIGNED_STATES | {"blocked"}:
            stream_state = stream.get("state")
            if stream_state and stream_state != task_state:
                errors.append(
                    f"{task_id}: task state {task_state} conflicts with workstream state {stream_state}"
                )
        if stream and task_state in ASSIGNED_STATES and volume in ("medium", "large"):
            worker = stream.get("worker") or stream.get("assignee")
            dispatcher = stream.get("dispatcher")
            if not worker:
                errors.append(f"{task_id}: {task_state} requires a worker")
            if not dispatcher:
                errors.append(
                    f"{task_id}: {task_state} requires a dispatcher started before the worker"
                )
            live_workers = {item.get("agent") for item in roles.get("workers") or []}
            live_dispatchers = {
                item.get("agent") for item in roles.get("dispatchers") or []
            }
            if worker and worker not in live_workers:
                errors.append(f"{task_id}: worker {worker} is not recorded in run.json")
            if dispatcher and dispatcher not in live_dispatchers:
                errors.append(
                    f"{task_id}: dispatcher {dispatcher} is not recorded in run.json"
                )
        if task_state == "in_review":
            receipt = (
                project
                / expand_layout(config, change=change, task=task_id)["worker_receipt"]
            )
            if not receipt.is_file():
                errors.append(f"{task_id}: in_review requires {receipt}")
        if task_state == "accepted":
            receipt = (
                project
                / expand_layout(config, change=change, task=task_id)[
                    "dispatcher_receipt"
                ]
            )
            if not receipt.is_file():
                errors.append(f"{task_id}: accepted requires {receipt}")
    if any(task.get("state") in ASSIGNED_STATES for task in tasks) and volume in (
        "medium",
        "large",
    ):
        if not (roles.get("orchestrator") or {}).get("pane_id"):
            errors.append(f"{volume} active work requires orchestrator in run.json")
        if not roles.get("dispatchers"):
            errors.append(f"{volume} active work requires dispatcher in run.json")
        if not roles.get("workers"):
            errors.append(f"{volume} active work requires worker in run.json")
        if not session.get("workspace_id"):
            errors.append(f"{volume} active work requires workspace_id in run.json")
    if volume == "large":
        file_sets: list[set[str]] = []
        for stream in workstreams:
            if not stream.get("worktree"):
                errors.append(
                    f"{stream.get('id', '<unknown>')}: large workstream requires worktree"
                )
            files = set(stream.get("files") or [])
            if not files:
                errors.append(
                    f"{stream.get('id', '<unknown>')}: large workstream requires file boundaries"
                )
            if any(files & existing for existing in file_sets):
                errors.append(
                    f"{stream.get('id', '<unknown>')}: large workstream file boundaries overlap"
                )
            file_sets.append(files)
    return {
        "ok": not errors,
        "errors": errors,
        "volume": volume,
        "runnable_tasks": len(runnable),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    before = sub.add_parser("preflight")
    before.add_argument("--project", required=True)
    before.add_argument("--volume", required=True)
    check = sub.add_parser("validate")
    check.add_argument("--project", required=True)
    check.add_argument("--change", required=True)
    args = parser.parse_args()
    project = Path(args.project).resolve()
    try:
        result = (
            preflight(project, args.volume)
            if args.command == "preflight"
            else validate(project, args.change)
        )
    except Exception as exc:
        result = {"ok": False, "errors": [str(exc)]}
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
