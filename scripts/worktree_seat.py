#!/usr/bin/env python3
"""Create or reuse a labeled Herdr worktree workspace for one large stream."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from herdr_cli import HerdrError, herdr, result_items, value_for
from load_config import resolve, workspace_label
from run_store import load_binding, load_identity, save_binding, save_identity


def _as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def ensure_worktree(
    *,
    project: Path,
    change: str,
    stream: str,
    branch: str,
    runner=None,
    config: dict | None = None,
) -> dict:
    config = config or resolve(project)
    identity = load_identity(project, change, config)
    session = identity.get("herdr_session")
    machine = identity.get("machine")
    if not branch:
        raise HerdrError("worktree create requires --branch", "missing_branch")
    label = workspace_label(
        config,
        repo=identity.get("repo") or project.name,
        change=change,
        stream=stream,
    )
    listed = herdr(
        ["worktree", "list", "--cwd", str(project)],
        session=session,
        machine=machine,
        runner=runner,
    )
    for item in result_items(listed, "worktrees"):
        live_branch = value_for(item, "branch", "git_branch")
        workspace_id = value_for(item, "open_workspace_id", "workspace_id")
        if live_branch == branch and workspace_id:
            cwd = _worktree_cwd(item)
            tab_id = value_for(item, "tab_id")
            pane_id = value_for(item, "root_pane_id", "pane_id")
            if not cwd or not pane_id:
                extra = _workspace_root(
                    workspace_id, session=session, machine=machine, runner=runner
                )
                cwd = cwd or extra.get("cwd")
                tab_id = tab_id or extra.get("tab_id")
                pane_id = pane_id or extra.get("pane_id")
            return {
                "action": "mapped",
                "workspace_id": workspace_id,
                "tab_id": tab_id,
                "pane_id": pane_id,
                "cwd": cwd,
                "branch": branch,
                "stream": stream,
                "label": label,
            }
    payload = herdr(
        [
            "worktree",
            "create",
            "--cwd",
            str(project),
            "--branch",
            branch,
            "--label",
            label,
            "--no-focus",
        ],
        session=session,
        machine=machine,
        runner=runner,
    )
    result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    workspace = _as_dict(result.get("workspace"))
    tab = _as_dict(result.get("tab"))
    root = _as_dict(result.get("root_pane"))
    workspace_id = value_for(workspace, "workspace_id") or value_for(
        result, "workspace_id"
    )
    tab_id = value_for(tab, "tab_id")
    pane_id = value_for(root, "pane_id")
    cwd = (
        _worktree_cwd(workspace)
        or _worktree_cwd(root)
        or _worktree_cwd(result)
        or value_for(result, "path", "cwd")
    )
    if not workspace_id:
        raise HerdrError("worktree create returned no workspace_id", "bad_json", payload)
    if not cwd:
        extra = _workspace_root(
            workspace_id, session=session, machine=machine, runner=runner
        )
        cwd = extra.get("cwd")
        tab_id = tab_id or extra.get("tab_id")
        pane_id = pane_id or extra.get("pane_id")
    binding = load_binding(project, change, config)
    created = binding.setdefault("created", {})
    workspaces = created.setdefault("workspaces", [])
    entry = {
        "workspace_id": workspace_id,
        "branch": branch,
        "stream": stream,
        "label": label,
        "tab_id": tab_id,
        "root_pane_id": pane_id,
    }
    existing = next(
        (
            item
            for item in workspaces
            if isinstance(item, dict) and item.get("workspace_id") == workspace_id
        ),
        None,
    )
    if existing is None:
        workspaces.append(entry)
    else:
        existing.update(entry)
    if tab_id:
        tabs = created.setdefault("tabs", [])
        if tab_id not in tabs and not any(
            isinstance(item, dict) and item.get("tab_id") == tab_id for item in tabs
        ):
            tabs.append({"tab_id": tab_id, "workspace_id": workspace_id, "stream": stream})
    save_binding(project, change, binding, config)
    if not identity.get("workspace_id"):
        identity["workspace_id"] = workspace_id
        identity["tab_id"] = tab_id or identity.get("tab_id") or ""
        save_identity(project, change, identity, config)
    return {
        "action": "created",
        "workspace_id": workspace_id,
        "tab_id": tab_id,
        "pane_id": pane_id,
        "cwd": cwd,
        "branch": branch,
        "stream": stream,
        "label": label,
    }


def _worktree_cwd(item: dict | None) -> str:
    return str(value_for(item, "cwd", "path", "worktree_path", "directory") or "")


def _workspace_root(
    workspace_id: str, *, session, machine, runner
) -> dict:
    payload = herdr(
        ["workspace", "get", workspace_id],
        session=session,
        machine=machine,
        runner=runner,
    )
    result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    workspace = result.get("workspace") if isinstance(result.get("workspace"), dict) else result
    cwd = _worktree_cwd(workspace) or _worktree_cwd(result)
    tab_id = value_for(workspace, "tab_id") or value_for(result, "tab_id")
    pane_id = value_for(workspace, "root_pane_id", "pane_id") or value_for(
        result, "root_pane_id", "pane_id"
    )
    if not pane_id:
        listed = herdr(
            ["pane", "list", "--workspace", workspace_id],
            session=session,
            machine=machine,
            runner=runner,
        )
        panes = result_items(listed, "panes")
        if panes:
            pane_id = value_for(panes[0], "pane_id")
            cwd = cwd or value_for(panes[0], "cwd")
            tab_id = tab_id or value_for(panes[0], "tab_id")
    return {"cwd": cwd, "tab_id": tab_id, "pane_id": pane_id}


def rollback_worktree(
    *,
    project: Path,
    change: str,
    workspace_id: str,
    runner=None,
    config: dict | None = None,
) -> dict:
    config = config or resolve(project)
    identity = load_identity(project, change, config)
    herdr(
        ["worktree", "remove", "--workspace", workspace_id, "--force"],
        session=identity.get("herdr_session"),
        machine=identity.get("machine"),
        runner=runner,
    )
    return {"action": "removed", "workspace_id": workspace_id}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--change", required=True)
    parser.add_argument("--stream", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--rollback-workspace", default="")
    args = parser.parse_args()
    project = Path(args.project).resolve()
    try:
        if args.rollback_workspace:
            result = rollback_worktree(
                project=project,
                change=args.change,
                workspace_id=args.rollback_workspace,
            )
        else:
            result = ensure_worktree(
                project=project,
                change=args.change,
                stream=args.stream,
                branch=args.branch,
            )
    except HerdrError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
