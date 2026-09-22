#!/usr/bin/env python3
"""Create one change folder: identity, binding, orchestration, artifacts, tasks."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from load_config import resolve, skill_dir
from run_store import (
    find_active_run,
    now_stamp,
    paths_for,
    upsert_index_run,
)
from yaml_lite import dump_yaml, load_yaml


CHANGE_NAME = re.compile(r"^[a-z][a-z0-9-]{0,47}$")


def exclude_local_runtime(project: Path) -> None:
    git_dir = project / ".git"
    if not git_dir.is_dir():
        return
    entry = "/.herdr/"
    exclude = git_dir / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if entry not in {line.strip() for line in existing.splitlines()}:
        prefix = "" if not existing or existing.endswith("\n") else "\n"
        exclude.write_text(existing + prefix + entry + "\n", encoding="utf-8")


def _repo_name(project: Path) -> str:
    return project.name or "repo"


def _pinned_session(value: str | None, env: dict) -> str:
    raw = (value if value is not None else env.get("HERDR_SESSION") or "default").strip()
    if raw == "":
        raise ValueError("herdr session must not be empty")
    return raw


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(dump_yaml(data), encoding="utf-8")
    temporary.replace(path)


def _create_if_missing(path: Path, data: dict, *, json_file: bool) -> str:
    if path.exists():
        return f"keep {path}"
    if json_file:
        _write_json(path, data)
    else:
        _write_yaml(path, data)
    return f"create {path}"


def init_work(
    project: Path,
    change: str,
    volume: str,
    *,
    session: str | None = None,
    machine: str | None = None,
    workspace: str | None = None,
    tab: str | None = None,
    repo: str | None = None,
    streams: list[str] | str | None = None,
    env: dict | None = None,
) -> dict:
    env = env or os.environ
    if not CHANGE_NAME.match(change):
        raise ValueError("change name must match [a-z][a-z0-9-]{0,47}")
    if not project.is_dir():
        raise ValueError(f"not a directory: {project}")
    config = resolve(project)
    graphs = config.get("graphs") or config.get("volumes") or {}
    if volume not in graphs:
        raise ValueError(f"unknown volume: {volume}")
    herdr_session = _pinned_session(session, env)
    machine_id = (machine if machine is not None else env.get("HERDR_MACHINE") or "local").strip() or "local"
    workspace_id = (
        workspace if workspace is not None else env.get("HERDR_WORKSPACE_ID") or ""
    ).strip()
    tab_id = (tab if tab is not None else env.get("HERDR_TAB_ID") or "").strip()
    repo_name = (repo or _repo_name(project)).strip()
    other = find_active_run(str(project.resolve()), herdr_session)
    if other and other.get("change") != change:
        raise ValueError(
            f"active run {other.get('change')} already exists for this project/session"
        )
    exclude_local_runtime(project)
    files = paths_for(project, change, config)
    for key in ("change_dir", "receipts"):
        files[key].mkdir(parents=True, exist_ok=True)
    stamp = now_stamp()
    identity = {
        "change": change,
        "volume": volume,
        "graph": volume,
        "project": str(project.resolve()),
        "repo": repo_name,
        "herdr_session": herdr_session,
        "machine": machine_id,
        "workspace_id": workspace_id,
        "tab_id": tab_id,
        "status": "active",
        "created_at": stamp,
    }
    stream_ids: list[str] = []
    if isinstance(streams, str) and streams.strip():
        stream_ids = [part.strip() for part in streams.split(",") if part.strip()]
    elif isinstance(streams, list):
        stream_ids = [str(part).strip() for part in streams if str(part).strip()]
    if stream_ids:
        identity["streams"] = stream_ids
    binding = {
        "change": change,
        "volume": volume,
        "graph": volume,
        "project": str(project.resolve()),
        "herdr_session": herdr_session,
        "machine": machine_id,
        "workspace_id": workspace_id,
        "tab_id": tab_id,
        "homes": {},
        "created": {"workspaces": [], "tabs": [], "panes": []},
        "nodes": {},
        "roles": {
            "brain": {"pane_id": "", "agent": None, "title": "Brain"},
            "orchestrator": {"pane_id": "", "agent": "", "title": "Orchestrator"},
            "dispatchers": [],
            "workers": [],
        },
    }
    orchestration = {
        "revision": 1,
        "current_node": "brain",
        "last_event": None,
        "updated_at": stamp,
        "updated_by": "brain",
        "history": [],
    }
    artifacts = {
        "revision": 1,
        "plan": None,
        "plan_revision": None,
        "spec": None,
        "adr": [],
        "requirements": [],
        "discovered": {},
        "updated_at": stamp,
    }
    assets = skill_dir() / "assets"
    tasks_template = assets / "tasks.template.yaml"
    if not tasks_template.is_file():
        tasks_template = assets / "state.template.yaml"
    tasks = load_yaml(tasks_template.read_text(encoding="utf-8")) if tasks_template.is_file() else {}
    if not isinstance(tasks, dict):
        tasks = {}
    tasks.setdefault("version", 1)
    tasks["workflow"] = volume
    tasks.setdefault("tasks", [])
    tasks.setdefault("workstreams", [])
    if stream_ids and not tasks["workstreams"]:
        tasks["workstreams"] = [{"id": stream} for stream in stream_ids]
    tasks.setdefault("sizing", {"reason": ""})
    tasks.setdefault(
        "constraints",
        {"push": False, "pr": False, "merge": False, "deploy": False, "close": False},
    )
    messages = [
        _create_if_missing(files["identity"], identity, json_file=False),
        _create_if_missing(files["session"], binding, json_file=True),
        _create_if_missing(files["orchestration"], orchestration, json_file=False),
        _create_if_missing(files["artifacts"], artifacts, json_file=False),
        _create_if_missing(files["state"], tasks, json_file=False),
    ]
    upsert_index_run(
        {
            "project": str(project.resolve()),
            "change": change,
            "herdr_session": herdr_session,
            "machine": machine_id,
            "volume": volume,
            "status": "active",
            "path": str(files["change_dir"]),
            "updated_at": stamp,
        }
    )
    return {
        "ok": True,
        "change_dir": str(files["change_dir"]),
        "herdr_session": herdr_session,
        "volume": volume,
        "files": messages,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--change", required=True)
    parser.add_argument("--volume", required=True, choices=("medium", "large"))
    parser.add_argument("--session", default=None)
    parser.add_argument("--machine", default=None)
    parser.add_argument("--workspace", default=None)
    parser.add_argument("--tab", default=None)
    parser.add_argument("--repo", default=None)
    parser.add_argument("--streams", default=None)
    args = parser.parse_args()
    project = Path(args.project).resolve()
    try:
        result = init_work(
            project,
            args.change,
            args.volume,
            session=args.session,
            machine=args.machine,
            workspace=args.workspace,
            tab=args.tab,
            repo=args.repo,
            streams=args.streams,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for line in result.get("files") or []:
        print(line)
    print(f"change_dir={result['change_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
