#!/usr/bin/env python3
"""Read or advance task state. Path comes from YAML layout.state."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from load_config import resolve
from run_store import bump, load_binding, load_tasks, save_tasks
from workflow_guard import validate

ASSIGNED_STATES = {"assigned", "running", "in_review", "rejected", "accepted"}


def _agent_from_run(session: dict, seat: str, number: int = 1) -> str:
    nodes = session.get("nodes") or {}
    entry = nodes.get(seat)
    items = entry if isinstance(entry, list) else ([entry] if isinstance(entry, dict) else [])
    numbered = [
        item
        for item in items
        if isinstance(item, dict) and item.get("agent") and item.get("number") == number
    ]
    if numbered:
        return str(numbered[0]["agent"])
    for item in items:
        if isinstance(item, dict) and item.get("agent"):
            return str(item["agent"])
    roles = session.get("roles") or {}
    extra = roles.get(seat) or roles.get(seat + "s") or []
    if isinstance(extra, dict):
        extra = [extra]
    for item in extra:
        if isinstance(item, dict) and item.get("agent"):
            return str(item["agent"])
    return ""


def find_task(state: dict, task_id: str) -> dict:
    for task in state.get("tasks") or []:
        if isinstance(task, dict) and task.get("id") == task_id:
            return task
    raise KeyError(f"unknown task {task_id}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--change", required=True)
    parser.add_argument("--dump", action="store_true")
    parser.add_argument("--task", default="")
    parser.add_argument("--set", dest="new_state", default="")
    parser.add_argument("--by", default="dispatcher")
    parser.add_argument("--worker", default="")
    parser.add_argument("--dispatcher", default="")
    args = parser.parse_args()
    project = Path(args.project).resolve()
    if args.change in (".", "..") or "/" in args.change or "\\" in args.change:
        print("error: --change must be a single folder name", file=sys.stderr)
        return 2
    try:
        config = resolve(project)
        state = load_tasks(project, args.change, config)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.dump and not args.task:
        json.dump(state, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if not args.task or not args.new_state:
        print("error: use --dump, or --task ID --set STATE", file=sys.stderr)
        return 2

    legal = set((config.get("task_states") or {}).keys())
    transitions = config.get("task_transitions") or {}
    if args.new_state not in legal:
        print(
            f"error: unknown state {args.new_state}. legal: {sorted(legal)}",
            file=sys.stderr,
        )
        return 2
    try:
        task = find_task(state, args.task)
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    current = task.get("state")
    allowed = transitions.get(current) or []
    if args.new_state != current and args.new_state not in allowed:
        print(
            f"error: illegal {current} -> {args.new_state}. allowed: {allowed}",
            file=sys.stderr,
        )
        return 3
    original = dict(state)
    original_tasks = [dict(item) for item in state.get("tasks") or []]
    original_streams = [dict(item) for item in state.get("workstreams") or []]
    task["state"] = args.new_state
    stream = next(
        (
            item
            for item in state.get("workstreams") or []
            if item.get("task") == args.task or item.get("id") == args.task
        ),
        None,
    )
    if stream:
        stream["state"] = args.new_state
        if args.new_state in ASSIGNED_STATES:
            session = load_binding(project, args.change, config)
            number = int(stream.get("id") or 1) if str(stream.get("id") or "").isdigit() else 1
            worker = args.worker or stream.get("worker") or _agent_from_run(session, "worker", number)
            dispatcher = (
                args.dispatcher
                or stream.get("dispatcher")
                or _agent_from_run(session, "dispatcher", number)
            )
            if worker:
                stream["worker"] = worker
            if dispatcher:
                stream["dispatcher"] = dispatcher
    bump(state, args.by)
    save_tasks(project, args.change, state, config)
    result = validate(project, args.change)
    if not result["ok"]:
        original["tasks"] = original_tasks
        original["workstreams"] = original_streams
        save_tasks(project, args.change, original, config)
        print(f"error: state validation failed: {result['errors']}", file=sys.stderr)
        return 4
    json.dump(task, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
