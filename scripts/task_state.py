#!/usr/bin/env python3
"""Read or advance task state. Path comes from YAML layout.state."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from load_config import expand_layout, resolve
from workflow_guard import validate
from yaml_lite import dump_yaml, load_yaml


def state_path(project: Path, config: dict, change: str) -> Path:
    rel = expand_layout(config, change=change).get("state")
    if not rel:
        raise ValueError("layout.state is missing from workflow YAML")
    return project / rel


def load_state(project: Path, config: dict, change: str) -> dict:
    path = state_path(project, config, change)
    if not path.is_file():
        raise FileNotFoundError(f"missing {path}")
    data = load_yaml(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("state.yaml must be a mapping")
    data.setdefault("tasks", [])
    data.setdefault("workstreams", [])
    data.setdefault("sizing", {})
    return data


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
    args = parser.parse_args()
    project = Path(args.project).resolve()
    if args.change in (".", "..") or "/" in args.change or "\\" in args.change:
        print("error: --change must be a single folder name", file=sys.stderr)
        return 2
    try:
        config = resolve(project)
        state = load_state(project, config, args.change)
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
    path = state_path(project, config, args.change)
    original = path.read_text(encoding="utf-8")
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
    path.write_text(dump_yaml(state), encoding="utf-8")
    result = validate(project, args.change)
    if not result["ok"]:
        path.write_text(original, encoding="utf-8")
        print(f"error: state validation failed: {result['errors']}", file=sys.stderr)
        return 4
    json.dump(task, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
