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
from workflow_guard import launch_command, preflight, resolve_command, validate
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
        plan: bool = True,
    ) -> None:
        change = root / ".herdr" / "runs" / "change"
        change.mkdir(parents=True)
        (change / "tasks.yaml").write_text(dump_yaml(state), encoding="utf-8")
        panes = []
        if active_roles:
            panes.append({"pane_id": "w1:p2", "status": "running"})
            for index in range(1, pairs + 1):
                panes.append({"pane_id": f"w{index}:p3", "status": "running"})
                panes.append({"pane_id": f"w{index}:p4", "status": "running"})
        run = {
            "volume": volume,
            "graph": volume,
            "herdr_session": "default",
            "workspace_id": "w1" if active_roles else "",
            "created": {
                "workspaces": [],
                "tabs": [],
                "panes": panes,
            },
            "nodes": {
                "orchestrator": (
                    {"pane_id": "w1:p2", "agent": "orchestrator"} if active_roles else {}
                ),
                "dispatcher": (
                    [
                        {"pane_id": f"w{index}:p3", "agent": f"dispatcher-{index}"}
                        for index in range(1, pairs + 1)
                    ]
                    if active_roles
                    else []
                ),
                "worker": (
                    [
                        {"pane_id": f"w{index}:p4", "agent": f"worker-{index}"}
                        for index in range(1, pairs + 1)
                    ]
                    if active_roles
                    else []
                ),
            },
            "roles": {
                "orchestrator": {"pane_id": "w1:p2" if active_roles else ""},
                "dispatchers": (
                    [
                        {"pane_id": f"w{index}:p3", "agent": f"dispatcher-{index}"}
                        for index in range(1, pairs + 1)
                    ]
                    if active_roles
                    else []
                ),
                "workers": (
                    [
                        {"pane_id": f"w{index}:p4", "agent": f"worker-{index}"}
                        for index in range(1, pairs + 1)
                    ]
                    if active_roles
                    else []
                ),
            },
        }
        (change / "run.json").write_text(json.dumps(run), encoding="utf-8")
        (change / "identity.yaml").write_text(
            dump_yaml(
                {
                    "change": "change",
                    "volume": volume,
                    "graph": volume,
                    "herdr_session": "default",
                    "workspace_id": "w1" if active_roles else "",
                    "status": "active",
                }
            ),
            encoding="utf-8",
        )
        (change / "orchestration.yaml").write_text(
            dump_yaml({"current_node": "dispatcher", "revision": 1}),
            encoding="utf-8",
        )
        assigned = any(
            task.get("state")
            in {"assigned", "running", "in_review", "rejected", "accepted"}
            for task in state.get("tasks") or []
        )
        if plan and assigned and volume != "small":
            plan_path = change / "plan.md"
            plan_path.write_text("# plan\n", encoding="utf-8")
            (change / "artifacts.yaml").write_text(
                dump_yaml(
                    {
                        "plan": str(plan_path.relative_to(root)).replace("\\", "/"),
                        "plan_revision": 1,
                    }
                ),
                encoding="utf-8",
            )
        else:
            (change / "artifacts.yaml").write_text(dump_yaml({"plan": None}), encoding="utf-8")
        herdr_dir = root / ".herdr"
        herdr_dir.mkdir(parents=True, exist_ok=True)
        (herdr_dir / "detection.yaml").write_text(
            dump_yaml(
                {
                    "systems": {
                        "requirements": {"sot": "Not used", "confidence": "high", "state": None},
                        "adr": {"sot": "Not used", "confidence": "high", "state": None},
                        "plans": {"sot": "Not used", "confidence": "high", "state": None},
                        "state": {"sot": "Not used", "confidence": "high", "state": None},
                    },
                    "open_design_decisions": False,
                    "independent_workstreams": 2 if volume == "large" else 1,
                    "sizing_graph": volume,
                    "sizing_reason": "test fixture",
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

    def test_resolver_accepts_existing_explicit_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "agent"
            executable.write_text("stub", encoding="utf-8")
            self.assertEqual(resolve_command(str(executable)), str(executable.resolve()))

    def test_resolver_rejects_missing_explicit_path(self) -> None:
        self.assertIsNone(resolve_command(str(Path("missing") / "agent")))

    def test_posix_resolver_uses_which(self) -> None:
        posix_os = mock.Mock(name="posix")
        with (
            mock.patch("workflow_guard.os", posix_os),
            mock.patch("workflow_guard.shutil.which", return_value="/usr/bin/codex"),
        ):
            self.assertEqual(resolve_command("codex"), "/usr/bin/codex")

    def test_windows_resolver_accepts_only_native_explicit_suffixes(self) -> None:
        with mock.patch("workflow_guard.shutil.which", return_value="C:/bin/codex.cmd"):
            self.assertEqual(
                resolve_command("codex.cmd"),
                str(Path("C:/bin/codex.cmd").resolve()),
            )
        with mock.patch(
            "workflow_guard.shutil.which", return_value="C:/bin/codex.ps1"
        ):
            self.assertIsNone(resolve_command("codex.ps1"))

    def test_windows_resolver_returns_none_when_command_is_missing(self) -> None:
        for path in ("", tempfile.gettempdir()):
            with self.subTest(path=path), mock.patch.dict(os.environ, {"PATH": path}):
                self.assertIsNone(resolve_command("missing-command"))

    def test_windows_launch_uses_exact_executable(self) -> None:
        with mock.patch.object(os, "name", "nt"):
            command = launch_command(
                r"C:\Program Files\Codex\codex.cmd",
                ["--model", "gpt-5.6-sol", "--no-alt-screen"],
            )
        self.assertEqual(
            command,
            "& 'C:\\Program Files\\Codex\\codex.cmd' '--model' 'gpt-5.6-sol' '--no-alt-screen'",
        )

    def test_windows_launch_escapes_single_quotes(self) -> None:
        with mock.patch.object(os, "name", "nt"):
            command = launch_command("C:/Sam's/codex.cmd", ["it's-safe"])
        self.assertEqual(command, "& 'C:/Sam''s/codex.cmd' 'it''s-safe'")

    def test_posix_launch_quotes_shell_arguments(self) -> None:
        posix_os = mock.Mock(name="posix")
        with mock.patch("workflow_guard.os", posix_os):
            command = launch_command("/opt/Codex CLI/codex", ["--model", "a'b"])
        self.assertEqual(command, "'/opt/Codex CLI/codex' --model 'a'\"'\"'b'")

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
                plan=False,
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
                plan=False,
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
                plan=False,
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

    def test_dispatch_without_plan_fails(self) -> None:
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
                plan=False,
            )
            result = validate(root, "change")
            self.assertFalse(result["ok"])
            self.assertTrue(
                any("artifacts.plan" in item or "from_plan" in item for item in result["errors"]),
                result["errors"],
            )

    def test_active_role_requires_running_recorded_pane(self) -> None:
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
            run_file = root / ".herdr" / "runs" / "change" / "run.json"
            run = json.loads(run_file.read_text(encoding="utf-8"))
            run["created"]["panes"] = [{"pane_id": "w1:p2", "status": "failed"}]
            run_file.write_text(json.dumps(run), encoding="utf-8")
            result = validate(root, "change")
            self.assertIn("pane w1:p2 is not running", result["errors"])
            self.assertIn(
                "pane w1:p3 is not recorded in created.panes", result["errors"]
            )

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
            state = (root / ".herdr" / "runs" / "change" / "tasks.yaml").read_text(
                encoding="utf-8"
            )
            self.assertEqual(state.count("state: blocked"), 2)

    def test_task_state_stamps_agents_from_run_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_run(
                root,
                "medium",
                {
                    "tasks": [{"id": "task-1", "state": "ready"}],
                    "workstreams": [
                        {"id": "stream-1", "task": "task-1", "state": "ready"}
                    ],
                },
                active_roles=True,
            )
            change = root / ".herdr" / "runs" / "change"
            plan_path = change / "plan.md"
            plan_path.write_text("# plan\n", encoding="utf-8")
            (change / "artifacts.yaml").write_text(
                dump_yaml(
                    {
                        "plan": str(plan_path.relative_to(root)).replace("\\", "/"),
                        "plan_revision": 1,
                    }
                ),
                encoding="utf-8",
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
                    "assigned",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            text = (root / ".herdr" / "runs" / "change" / "tasks.yaml").read_text(
                encoding="utf-8"
            )
            self.assertIn("dispatcher: dispatcher-1", text)
            self.assertIn("worker: worker-1", text)
            self.assertIn("state: assigned", text)

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

    def test_preflight_rejects_exhausted_usage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = {
                "HERDR_ENV": "1",
                "WORKFLOW_HERDR_USAGE_JSON": json.dumps({"remaining": 0}),
            }
            with mock.patch("workflow_guard.resolve_command", return_value="C:/bin/x.exe"):
                result = preflight(root, "medium", change="c1", env=env)
            self.assertFalse(result["ok"])
            self.assertTrue(any("usage exhausted" in item for item in result["errors"]))

    def test_preflight_unknown_volume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = preflight(Path(directory), "gigantic", env={"HERDR_ENV": "1"})
            self.assertFalse(result["ok"])
            self.assertIn("unknown volume: gigantic", result["errors"])


if __name__ == "__main__":
    unittest.main()
