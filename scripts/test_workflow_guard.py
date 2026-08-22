from __future__ import annotations

import os
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from init_work import exclude_local_runtime
from workflow_guard import resolve_command, validate
from yaml_lite import dump_yaml


class WorkflowGuardTests(unittest.TestCase):
    def test_local_runtime_uses_git_info_exclude(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git" / "info").mkdir(parents=True)
            exclude_local_runtime(root)
            exclude_local_runtime(root)
            self.assertEqual(
                (root / ".git" / "info" / "exclude").read_text(encoding="utf-8"),
                "/.herdr/\n",
            )
            self.assertFalse((root / ".gitignore").exists())

    def write_run(
        self,
        root: Path,
        volume: str,
        state: dict,
        *,
        active_roles: bool = False,
        pairs: int = 1,
    ) -> None:
        change = root / ".herdr" / "runs" / "change"
        change.mkdir(parents=True)
        (change / "state.yaml").write_text(dump_yaml(state), encoding="utf-8")
        (change / "run.json").write_text(
            json.dumps(
                {
                    "volume": volume,
                    "workspace_id": "w1" if active_roles else "",
                    "created": {"workspaces": [], "tabs": [], "panes": []},
                    "roles": {
                        "orchestrator": {"pane_id": "w1:p2" if active_roles else ""},
                        "dispatchers": (
                            [
                                {
                                    "pane_id": f"w{index}:p3",
                                    "agent": f"dispatcher-{index}",
                                }
                                for index in range(1, pairs + 1)
                            ]
                            if active_roles
                            else []
                        ),
                        "workers": (
                            [
                                {
                                    "pane_id": f"w{index}:p4",
                                    "agent": f"worker-{index}",
                                }
                                for index in range(1, pairs + 1)
                            ]
                            if active_roles
                            else []
                        ),
                    },
                }
            ),
            encoding="utf-8",
        )

    def test_windows_resolver_prefers_native_suffixes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("codex", "codex.ps1", "codex.cmd", "codex.exe"):
                (root / name).write_text("stub", encoding="utf-8")
            with (
                mock.patch.object(os, "name", "nt"),
                mock.patch.dict(os.environ, {"PATH": str(root)}),
            ):
                self.assertEqual(
                    resolve_command("codex"), str((root / "codex.exe").resolve())
                )

    def test_windows_resolver_uses_cmd_without_exe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "codex").write_text("#!/bin/sh", encoding="utf-8")
            (root / "codex.ps1").write_text("#!/usr/bin/env pwsh", encoding="utf-8")
            (root / "codex.cmd").write_text("@echo off", encoding="utf-8")
            with (
                mock.patch.object(os, "name", "nt"),
                mock.patch.dict(os.environ, {"PATH": str(root)}),
            ):
                self.assertEqual(
                    resolve_command("codex"), str((root / "codex.cmd").resolve())
                )

    def test_large_requires_two_runnable_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_run(
                root,
                "large",
                {
                    "tasks": [
                        {"id": "active", "state": "ready"},
                        {"id": "missing", "state": "blocked"},
                    ],
                    "workstreams": [],
                },
            )
            result = validate(root, "change")
            self.assertFalse(result["ok"])
            self.assertIn(
                "large requires at least two runnable tasks", result["errors"]
            )

    def test_medium_rejects_worktree_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_run(
                root,
                "medium",
                {
                    "tasks": [{"id": "task-1", "state": "running"}],
                    "workstreams": [
                        {
                            "id": "task-1",
                            "task": "task-1",
                            "worktree": "C:/tmp/worktree",
                        }
                    ],
                },
            )
            result = validate(root, "change")
            self.assertFalse(result["ok"])
            self.assertIn(
                "medium forbids worktrees/worktree workspaces", result["errors"]
            )

    def test_medium_requires_dispatcher_before_running_worker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_run(
                root,
                "medium",
                {
                    "tasks": [{"id": "task-1", "state": "running"}],
                    "workstreams": [
                        {
                            "id": "stream-1",
                            "task": "task-1",
                            "worker": "worker-1",
                            "state": "running",
                        }
                    ],
                },
                active_roles=True,
            )
            result = validate(root, "change")
            self.assertFalse(result["ok"])
            self.assertIn(
                "task-1: running requires a dispatcher started before the worker",
                result["errors"],
            )

    def test_blocked_task_rejects_running_workstream(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_run(
                root,
                "medium",
                {
                    "tasks": [{"id": "task-1", "state": "blocked"}],
                    "workstreams": [
                        {"id": "stream-1", "task": "task-1", "state": "running"}
                    ],
                },
            )
            result = validate(root, "change")
            self.assertFalse(result["ok"])
            self.assertIn(
                "task-1: task state blocked conflicts with workstream state running",
                result["errors"],
            )

    def test_terminal_tasks_are_not_runnable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_run(
                root,
                "medium",
                {
                    "tasks": [
                        {"id": "done", "state": "closed"},
                        {"id": "waiting", "state": "pending"},
                    ],
                    "workstreams": [],
                },
            )
            result = validate(root, "change")
            self.assertEqual(result["runnable_tasks"], 0)

    def test_valid_medium_pair_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_run(
                root,
                "medium",
                {
                    "tasks": [{"id": "task-1", "state": "running"}],
                    "workstreams": [
                        {
                            "id": "stream-1",
                            "task": "task-1",
                            "dispatcher": "dispatcher-1",
                            "worker": "worker-1",
                            "state": "running",
                        }
                    ],
                },
                active_roles=True,
            )
            result = validate(root, "change")
            self.assertTrue(result["ok"], result["errors"])

    def test_task_state_keeps_workstream_in_sync(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_run(
                root,
                "medium",
                {
                    "tasks": [{"id": "task-1", "state": "running"}],
                    "workstreams": [
                        {
                            "id": "stream-1",
                            "task": "task-1",
                            "dispatcher": "dispatcher-1",
                            "worker": "worker-1",
                            "state": "running",
                        }
                    ],
                },
                active_roles=True,
            )
            proc = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).with_name("task_state.py")),
                    "--project",
                    str(root),
                    "--change",
                    "change",
                    "--task",
                    "task-1",
                    "--set",
                    "blocked",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            state = (root / ".herdr" / "runs" / "change" / "state.yaml").read_text(
                encoding="utf-8"
            )
            self.assertEqual(state.count("state: blocked"), 2)

    def test_valid_large_pairs_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_run(
                root,
                "large",
                {
                    "tasks": [
                        {"id": "task-1", "state": "running"},
                        {"id": "task-2", "state": "running"},
                    ],
                    "workstreams": [
                        {
                            "id": "stream-1",
                            "task": "task-1",
                            "dispatcher": "dispatcher-1",
                            "worker": "worker-1",
                            "state": "running",
                            "worktree": "C:/tmp/stream-1",
                            "files": ["src/a.py"],
                        },
                        {
                            "id": "stream-2",
                            "task": "task-2",
                            "dispatcher": "dispatcher-2",
                            "worker": "worker-2",
                            "state": "running",
                            "worktree": "C:/tmp/stream-2",
                            "files": ["src/b.py"],
                        },
                    ],
                },
                active_roles=True,
                pairs=2,
            )
            result = validate(root, "change")
            self.assertTrue(result["ok"], result["errors"])

    def test_large_passes_after_streams_are_accepted(self) -> None:
        for states in (("accepted", "running"), ("accepted", "accepted")):
            with self.subTest(states=states), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.write_run(
                    root,
                    "large",
                    {
                        "tasks": [
                            {"id": f"task-{index}", "state": state}
                            for index, state in enumerate(states, 1)
                        ],
                        "workstreams": [
                            {
                                "id": f"stream-{index}",
                                "task": f"task-{index}",
                                "dispatcher": f"dispatcher-{index}",
                                "worker": f"worker-{index}",
                                "state": state,
                                "worktree": f"C:/tmp/stream-{index}",
                                "files": [f"src/{index}.py"],
                            }
                            for index, state in enumerate(states, 1)
                        ],
                    },
                    active_roles=True,
                    pairs=2,
                )
                receipts = root / ".herdr" / "runs" / "change" / "receipts"
                receipts.mkdir(parents=True, exist_ok=True)
                for index, state in enumerate(states, 1):
                    if state == "accepted":
                        (receipts / f"task-{index}.dispatcher.md").write_text(
                            "accepted", encoding="utf-8"
                        )
                result = validate(root, "change")
                self.assertTrue(result["ok"], result["errors"])


if __name__ == "__main__":
    unittest.main()
