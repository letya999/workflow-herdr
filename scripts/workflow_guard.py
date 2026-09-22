#!/usr/bin/env python3
"""Fail-fast checks before and during a workflow-herdr run."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from herdr_cli import HerdrError, assert_session_pin, herdr, result_items, value_for
from load_config import (
    AGENT_NAME_RE,
    KIND_RE,
    agent_name,
    expand_layout,
    graph_of,
    native_args,
    node_of,
    resolve,
    validate_graph,
)
from run_store import (
    find_active_run,
    load_artifacts,
    load_binding,
    load_identity,
    load_orchestration,
    load_tasks,
    paths_for,
)
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


def preflight(
    project: Path,
    volume: str,
    *,
    change: str = "",
    env: dict | None = None,
) -> dict:
    env = env or os.environ
    config = resolve(project)
    graph = graph_of(config, volume) or (config.get("volumes") or {}).get(volume) or {}
    errors: list[str] = []
    warnings: list[str] = []
    seats: dict[str, dict] = {}
    if not graph:
        return {
            "ok": False,
            "errors": [f"unknown volume: {volume}"],
            "warnings": warnings,
            "seats": seats,
        }
    errors.extend(validate_graph(config, volume))
    if env.get("HERDR_ENV") != "1":
        errors.append("HERDR_ENV must be 1")
    if not resolve_command("herdr"):
        errors.append("herdr is not executable")
    live_session = (env.get("HERDR_SESSION") or "").strip()
    if live_session == "":
        warnings.append("HERDR_SESSION unset; identity will pin default")
    node_ids = list(graph.get("nodes") or graph.get("seats") or [])
    for seat in node_ids:
        node = node_of(config, seat)
        harness_name = node.get("harness") or node.get("cli")
        if not node.get("start", True) or harness_name == "human":
            continue
        harness = (config.get("harnesses") or {}).get(harness_name) or {}
        kind = harness.get("kind")
        resolved = resolve_command(str(harness_name))
        args = native_args(config, seat, 1, change)
        name = agent_name(config, seat, 1, change)
        seat_info = {
            "command": harness_name,
            "resolved": resolved,
            "kind": kind,
            "agent_name": name,
            "model": node.get("model"),
            "effort": node.get("effort"),
            "launch": launch_command(resolved, args) if resolved else None,
        }
        seats[seat] = seat_info
        if not resolved:
            errors.append(f"{seat}: no safe executable for {harness_name}")
        if kind and not KIND_RE.match(str(kind)):
            errors.append(f"{seat}: invalid Herdr kind {kind}")
        if name and not AGENT_NAME_RE.match(name):
            errors.append(f"{seat}: invalid agent name {name}")
        efforts = harness.get("efforts") or []
        effort = node.get("effort")
        if efforts and effort and effort not in efforts:
            errors.append(f"{seat}: effort {effort} is not valid for {harness_name}")
        if node.get("model") in (None, ""):
            errors.append(f"{seat}: model is missing")
    usage = _usage_status(env)
    if usage.get("exhausted"):
        errors.append(f"usage exhausted: {usage.get('detail')}")
    elif usage.get("warning"):
        warnings.append(str(usage["warning"]))
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "seats": seats,
        "volume": volume,
        "graph": volume,
    }


def _usage_status(env: dict) -> dict:
    raw = env.get("WORKFLOW_HERDR_USAGE_JSON")
    if not raw:
        return {"warning": "usage not probed (set WORKFLOW_HERDR_USAGE_JSON or install a quota tool)"}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"warning": "usage JSON is invalid"}
    if data.get("remaining") in (0, "0", 0.0) or data.get("exhausted") is True:
        return {"exhausted": True, "detail": data.get("detail") or "remaining=0"}
    return data if isinstance(data, dict) else {}


def _tasks_and_binding(project: Path, change: str, config: dict) -> tuple[dict, dict, dict]:
    files = paths_for(project, change, config)
    state_path = files["state"]
    if not state_path.is_file() and (files["change_dir"] / "state.yaml").is_file():
        state = load_yaml((files["change_dir"] / "state.yaml").read_text(encoding="utf-8")) or {}
    else:
        state = load_tasks(project, change, config)
    session = load_binding(project, change, config)
    identity = load_identity(project, change, config)
    return state if isinstance(state, dict) else {}, session, identity


def _binding_nodes(session: dict) -> dict:
    nodes = dict(session.get("nodes") or {})
    roles = session.get("roles") or {}
    if "orchestrator" in roles and "orchestrator" not in nodes:
        nodes["orchestrator"] = roles.get("orchestrator") or {}
    if roles.get("dispatchers") and "dispatcher" not in nodes:
        nodes["dispatcher"] = roles.get("dispatchers")
    if roles.get("workers") and "worker" not in nodes:
        nodes["worker"] = roles.get("workers")
    return nodes


def _agent_entries(nodes: dict, seat: str) -> list[dict]:
    value = nodes.get(seat)
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict) and value:
        return [value]
    return []


def _agents_named(nodes: dict, session: dict, seat: str, role_key: str) -> set:
    names: list = []
    for item in _agent_entries(nodes, seat):
        names.append(item.get("agent"))
    extra = (session.get("roles") or {}).get(role_key) or []
    if isinstance(extra, dict):
        extra = [extra]
    for item in extra:
        if isinstance(item, dict):
            names.append(item.get("agent"))
    return {name for name in names if name}


def validate(project: Path, change: str, *, env: dict | None = None) -> dict:
    env = env or os.environ
    config = resolve(project)
    files = paths_for(project, change, config)
    state, session, identity = _tasks_and_binding(project, change, config)
    errors: list[str] = []
    volume = (
        identity.get("volume")
        or session.get("volume")
        or state.get("volume")
        or state.get("workflow")
    )
    graph = graph_of(config, volume) if volume else {}
    recipe = graph or (config.get("volumes") or {}).get(volume) or {}
    tasks = state.get("tasks") or []
    legal_states = set((config.get("task_states") or {}).keys())
    runnable = [task for task in tasks if task.get("state") in RUNNABLE_STATES]
    workstreams = state.get("workstreams") or []
    created = session.get("created") or {}
    created_workspaces = created.get("workspaces") or []
    created_tabs = created.get("tabs") or []
    created_panes = created.get("panes") or []
    pane_status = {
        item.get("pane_id") if isinstance(item, dict) else item: (
            item.get("status") if isinstance(item, dict) else None
        )
        for item in created_panes
    }
    nodes = _binding_nodes(session)
    if volume not in (config.get("graphs") or {}) and volume not in (config.get("volumes") or {}):
        errors.append(f"unknown volume: {volume}")
    elif volume:
        errors.extend(validate_graph(config, volume))
    if volume == "large":
        min_tasks = int((config.get("guards") or {}).get("large_min_runnable_tasks") or 2)
        if workstreams and len(workstreams) < min_tasks:
            errors.append("large requires at least two workstreams")
        elif not workstreams and len(runnable) < min_tasks:
            errors.append("large requires at least two runnable tasks")
    if volume == "medium" and created_workspaces:
        errors.append("medium must stay in the current workspace")
    if recipe.get("worktrees") is False and (workstreams or created_workspaces):
        if any(stream.get("worktree") for stream in workstreams) or created_workspaces:
            errors.append(f"{volume} forbids worktrees/worktree workspaces")
    wanted_session = (identity.get("herdr_session") or session.get("herdr_session") or "").strip()
    try:
        assert_session_pin(wanted_session, env)
    except HerdrError as exc:
        errors.append(str(exc))
    artifacts = load_artifacts(project, change, config) if files["artifacts"].is_file() else {}
    orchestration = (
        load_orchestration(project, change, config) if files["orchestration"].is_file() else {}
    )
    guards = config.get("guards") or {}
    assigned_exists = any(task.get("state") in ASSIGNED_STATES for task in tasks)
    if guards.get("require_detection") and volume not in (None, "small"):
        detection_rel = expand_layout(config, change=change).get("detection") or ".herdr/detection.yaml"
        detection_path = project / detection_rel
        if not detection_path.is_file():
            errors.append("dispatch requires .herdr/detection.yaml (run detect + Brain classify)")
        else:
            detected = load_yaml(detection_path.read_text(encoding="utf-8")) or {}
            if not detected.get("sizing_reason"):
                errors.append("detection.yaml missing sizing_reason")
            graph_name = detected.get("sizing_graph")
            if graph_name and graph_name != volume:
                errors.append(
                    f"detection sizing_graph {graph_name} does not match run volume {volume}"
                )
            if detected.get("independent_workstreams") == 0:
                errors.append("detection independent_workstreams must be >= 1")

    if (
        guards.get("require_plan_before_dispatch")
        and volume not in (None, "small")
        and assigned_exists
    ):
        plan_path = artifacts.get("plan")
        if not plan_path:
            errors.append("dispatch requires artifacts.plan")
        elif not (project / str(plan_path)).is_file() and not Path(str(plan_path)).is_file():
            errors.append(f"plan file missing: {plan_path}")

    task_ids = [task.get("id") for task in tasks]
    if None in task_ids or len(task_ids) != len(set(task_ids)):
        errors.append("tasks require unique non-empty ids")
    stream_ids = [stream.get("id") for stream in workstreams]
    if None in stream_ids or len(stream_ids) != len(set(stream_ids)):
        errors.append("workstreams require unique non-empty ids")
    live_workers = _agents_named(nodes, session, "worker", "workers")
    live_dispatchers = _agents_named(nodes, session, "dispatcher", "dispatchers")
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
        if task.get("state") in ASSIGNED_STATES and volume not in (None, "small"):
            if not task.get("from_plan") and not (artifacts.get("plan")):
                errors.append(f"{task_id}: assigned work requires from_plan or artifacts.plan")
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
            if worker and worker not in live_workers:
                errors.append(f"{task_id}: worker {worker} is not recorded in run.json")
            if dispatcher and dispatcher not in live_dispatchers:
                errors.append(
                    f"{task_id}: dispatcher {dispatcher} is not recorded in run.json"
                )
        if task_state == "in_review":
            receipt = project / expand_layout(config, change=change, task=task_id)["worker_receipt"]
            if not receipt.is_file():
                errors.append(f"{task_id}: in_review requires {receipt}")
        if task_state == "accepted":
            receipt = (
                project
                / expand_layout(config, change=change, task=task_id)["dispatcher_receipt"]
            )
            if not receipt.is_file():
                errors.append(f"{task_id}: accepted requires {receipt}")
    if any(task.get("state") in ASSIGNED_STATES for task in tasks) and volume in (
        "medium",
        "large",
    ):
        orch = _agent_entries(nodes, "orchestrator")
        if not orch and not (nodes.get("orchestrator") or {}).get("pane_id"):
            if not ((session.get("roles") or {}).get("orchestrator") or {}).get("pane_id"):
                errors.append(f"{volume} active work requires orchestrator in run.json")
        if not _agent_entries(nodes, "dispatcher") and not (session.get("roles") or {}).get(
            "dispatchers"
        ):
            errors.append(f"{volume} active work requires dispatcher in run.json")
        if not _agent_entries(nodes, "worker") and not (session.get("roles") or {}).get("workers"):
            errors.append(f"{volume} active work requires worker in run.json")
        if not (identity.get("workspace_id") or session.get("workspace_id")):
            errors.append(f"{volume} active work requires workspace_id in run.json")
        active_roles = _agent_entries(nodes, "orchestrator")
        active_roles += _agent_entries(nodes, "dispatcher")
        active_roles += _agent_entries(nodes, "worker")
        if not active_roles:
            roles = session.get("roles") or {}
            active_roles = [roles.get("orchestrator") or {}]
            active_roles += roles.get("dispatchers") or []
            active_roles += roles.get("workers") or []
        for role in active_roles:
            pane_id = role.get("pane_id")
            if pane_id and pane_id not in pane_status:
                errors.append(f"pane {pane_id} is not recorded in created.panes")
            elif pane_id and pane_status[pane_id] != "running":
                errors.append(f"pane {pane_id} is not running")
    if volume == "large":
        file_sets: list[set[str]] = []
        for stream in workstreams:
            if not stream.get("worktree"):
                errors.append(
                    f"{stream.get('id', '<unknown>')}: large workstream requires worktree"
                )
            fileset = set(stream.get("files") or [])
            if not fileset:
                errors.append(
                    f"{stream.get('id', '<unknown>')}: large workstream requires file boundaries"
                )
            if any(fileset & existing for existing in file_sets):
                errors.append(
                    f"{stream.get('id', '<unknown>')}: large workstream file boundaries overlap"
                )
            file_sets.append(fileset)
    return {
        "ok": not errors,
        "errors": errors,
        "volume": volume,
        "runnable_tasks": len(runnable),
        "orchestration": orchestration.get("current_node"),
    }


def doctor(
    project: Path,
    change: str = "",
    *,
    volume: str = "",
    env: dict | None = None,
    runner=None,
    live: bool = True,
    inventories=None,
    kinds: list[str] | None = None,
    protocol=None,
) -> dict:
    env = env or os.environ
    config = resolve(project)
    identity = load_identity(project, change, config) if change else {}
    session = load_binding(project, change, config) if change else {}
    volume = (
        volume
        or identity.get("volume")
        or session.get("volume")
        or ""
    )
    if volume:
        result = preflight(project, volume, change=change, env=env)
    else:
        result = {
            "ok": True,
            "errors": [],
            "warnings": [],
            "seats": {},
            "volume": None,
        }
        if env.get("HERDR_ENV") != "1":
            result["errors"].append("HERDR_ENV must be 1")
            result["ok"] = False
        if not resolve_command("herdr"):
            result["errors"].append("herdr is not executable")
            result["ok"] = False
    checks = [{"ok": result["ok"], "label": "preflight", "errors": list(result["errors"])}]
    if live:
        from probe import herdr_protocol, probe_seats

        proto = protocol if protocol is not None else herdr_protocol()
        result["protocol"] = proto
        if not proto.get("ok"):
            result["errors"].extend(proto.get("errors") or [])
            checks.append(
                {
                    "ok": False,
                    "label": "herdr protocol",
                    "errors": proto.get("errors") or [],
                    "fix": proto.get("fix"),
                }
            )
        else:
            checks.append({"ok": True, "label": "herdr protocol"})

        probed = probe_seats(
            config,
            volume=volume or None,
            kinds=kinds,
            inventories=inventories,
        )
        result.setdefault("warnings", []).extend(probed.get("warnings") or [])
        result["errors"].extend(probed.get("errors") or [])
        result["seats"] = probed.get("seats") or result.get("seats")
        result["kinds"] = probed.get("kinds")
        checks.append(
            {
                "ok": probed.get("ok"),
                "label": "live harness/model/effort",
                "errors": probed.get("errors") or [],
            }
        )
    wanted = (identity.get("herdr_session") or env.get("HERDR_SESSION") or "default").strip()
    try:
        assert_session_pin(wanted, env)
        checks.append({"ok": True, "label": f"session pin {wanted or 'default'}"})
    except HerdrError as exc:
        checks.append({"ok": False, "label": "session pin", "fix": str(exc)})
        result["errors"].append(str(exc))
    workspace_id = identity.get("workspace_id") or session.get("workspace_id")
    cwd_ok = True
    if workspace_id and runner is not None:
        try:
            payload = herdr(
                ["workspace", "get", workspace_id],
                session=identity.get("herdr_session"),
                machine=identity.get("machine"),
                runner=runner,
            )
            cwd = value_for(payload.get("result") or payload, "cwd", "path")
            if cwd and Path(str(cwd)).resolve() != project.resolve():
                cwd_ok = False
                result["errors"].append(
                    f"workspace {workspace_id} cwd {cwd} is not {project}"
                )
        except HerdrError as exc:
            cwd_ok = False
            result["errors"].append(str(exc))
    checks.append({"ok": cwd_ok, "label": "workspace cwd"})
    if change:
        other = find_active_run(str(project.resolve()), wanted, None)
        if other and other.get("change") != change and other.get("status") == "active":
            result["errors"].append(
                f"active run {other.get('change')} already exists for this project/session"
            )
            checks.append({"ok": False, "label": "one active run"})
        else:
            checks.append({"ok": True, "label": "one active run"})
    result["ok"] = not result["errors"]
    result["checks"] = checks
    return result


def status_map(project: Path, change: str, *, runner=None) -> dict:
    config = resolve(project)
    identity = load_identity(project, change, config)
    session = load_binding(project, change, config)
    created = (session.get("created") or {}).get("workspaces") or []
    mapped = []
    orphan = []
    live_ids = set()
    if runner is not None:
        try:
            payload = herdr(
                ["worktree", "list"],
                session=identity.get("herdr_session"),
                machine=identity.get("machine"),
                runner=runner,
            )
            for item in result_items(payload, "worktrees"):
                live_ids.add(value_for(item, "open_workspace_id", "workspace_id"))
        except HerdrError:
            live_ids = set()
    for item in created:
        ws_id = item if isinstance(item, str) else item.get("workspace_id")
        entry = {"workspace_id": ws_id, "status": "mapped"}
        if live_ids and ws_id not in live_ids:
            entry["status"] = "orphan"
            orphan.append(entry)
        else:
            mapped.append(entry)
    return {"ok": not orphan, "mapped": mapped, "orphan_workspaces": orphan}


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    before = sub.add_parser("preflight")
    before.add_argument("--project", required=True)
    before.add_argument("--volume", required=True)
    before.add_argument("--change", default="")
    check = sub.add_parser("validate")
    check.add_argument("--project", required=True)
    check.add_argument("--change", required=True)
    doc = sub.add_parser("doctor")
    doc.add_argument("--project", required=True)
    doc.add_argument("--change", default="")
    doc.add_argument("--volume", default="")
    mapped = sub.add_parser("status")
    mapped.add_argument("--project", required=True)
    mapped.add_argument("--change", required=True)
    args = parser.parse_args()
    project = Path(args.project).resolve()
    try:
        if args.command == "preflight":
            result = preflight(project, args.volume, change=args.change)
        elif args.command == "validate":
            result = validate(project, args.change)
        elif args.command == "doctor":
            result = doctor(project, args.change, volume=args.volume)
        else:
            result = status_map(project, args.change)
    except Exception as exc:
        result = {"ok": False, "errors": [str(exc)]}
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
