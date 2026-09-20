from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from discover import discover
from herdr_cli import HerdrError
from init_work import init_work
from label_seat import label_seat
from orchestrate import advance
from run_store import find_active_run, load_index, load_orchestration, save_index
from worktree_seat import ensure_worktree
def _cmd(args: list[str]) -> list[str]:
    if len(args) >= 2 and args[0] in ("--session", "--machine"):
        return args[2:]
    return args


class BodwTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.index = self.root / "index.yaml"
        os.environ["WORKFLOW_HERDR_INDEX"] = str(self.index)
        self.addCleanup(self.tmp.cleanup)

    def test_brain_handoff_does_not_wait(self) -> None:
        init_work(self.root, "login", "medium", session="s1")
        result = advance(self.root, "login", "brain", "goal_created")
        self.assertEqual(result["to"], ["orchestrator"])
        self.assertFalse(result["may_wait"])
        self.assertFalse(result["brain_waits"])
        self.assertIn("without --wait", result["prompt"])
        orch = load_orchestration(self.root, "login")
        self.assertEqual(orch["current_node"], "orchestrator")
        result = advance(self.root, "login", "orchestrator", "task_ready")
        self.assertTrue(result["may_wait"])
        self.assertEqual(result["to"], ["dispatcher"])
        result = advance(self.root, "login", "dispatcher", "assigned")
        self.assertEqual(result["to"], ["worker"])
        result = advance(self.root, "login", "worker", "progress")
        self.assertTrue(result["loop"])
        self.assertEqual(result["to"], ["dispatcher"])
        result = advance(self.root, "login", "dispatcher", "correction")
        self.assertTrue(result["loop"])
        self.assertEqual(result["to"], ["worker"])
        result = advance(self.root, "login", "dispatcher", "accepted")
        self.assertEqual(result["to"], ["orchestrator"])
        data = load_index()
        for item in data.get("runs") or []:
            if item.get("change") == "login":
                item["updated_at"] = "2000-01-01T00:00:00Z"
        save_index(data)
        result = advance(self.root, "login", "orchestrator", "plan_closed")
        self.assertEqual(result["to"], ["brain"])
        self.assertEqual(find_active_run(str(self.root.resolve()), "s1"), None)
        closed = next(
            item for item in load_index().get("runs") or [] if item.get("change") == "login"
        )
        self.assertEqual(closed["status"], "closed")
        self.assertNotEqual(closed.get("updated_at"), "2000-01-01T00:00:00Z")

    def test_illegal_brain_to_worker_on_medium(self) -> None:
        init_work(self.root, "login", "medium")
        with self.assertRaisesRegex(ValueError, "no transition brain -\\[assigned\\]->"):
            advance(self.root, "login", "brain", "assigned")

    def test_one_active_run_per_session_project(self) -> None:
        init_work(self.root, "one", "medium", session="s1")
        with self.assertRaisesRegex(ValueError, "active run one already exists"):
            init_work(self.root, "two", "medium", session="s1")
        init_work(self.root, "two", "medium", session="s2")

    def test_discover_lists_adr_and_specs(self) -> None:
        (self.root / "docs" / "adr").mkdir(parents=True)
        (self.root / "docs" / "adr" / "0001.md").write_text("adr", encoding="utf-8")
        (self.root / "specs").mkdir()
        (self.root / "specs" / "login.md").write_text("spec", encoding="utf-8")
        result = discover(self.root)
        adr_files = []
        for item in result["groups"]["adr"]:
            adr_files.extend(item["files"])
        spec_files = []
        for item in result["groups"]["requirements"]:
            spec_files.extend(item["files"])
        self.assertIn("docs/adr/0001.md", adr_files)
        self.assertIn("specs/login.md", spec_files)
        self.assertFalse(result["profile_exists"])

    def test_label_seat_renames_pane_and_tab_not_workspace_on_medium(self) -> None:
        init_work(
            self.root,
            "login",
            "medium",
            session="s1",
            workspace="w1",
            tab="w1:t1",
            repo="demo",
        )
        calls: list[list[str]] = []

        def runner(args: list[str]) -> dict:
            calls.append(_cmd(args))
            return {}

        result = label_seat(
            project=self.root,
            change="login",
            seat="orchestrator",
            pane_id="w1:p2",
            runner=runner,
        )
        self.assertIn("Orchestrator", result["pane_label"])
        self.assertEqual(result["tab_label"], "login")
        self.assertIsNone(result["workspace_label"])
        self.assertTrue(any(call[:2] == ["pane", "rename"] for call in calls))
        self.assertTrue(any(call[:2] == ["tab", "rename"] for call in calls))
        self.assertFalse(any(call[:2] == ["workspace", "rename"] for call in calls))

    def test_worktree_create_always_passes_cwd_branch_label(self) -> None:
        init_work(self.root, "login", "large", session="s1", repo="demo")
        calls: list[list[str]] = []

        def runner(args: list[str]) -> dict:
            cmd = _cmd(args)
            calls.append(cmd)
            if cmd[:2] == ["worktree", "list"]:
                return {"result": {"worktrees": []}}
            if cmd[:2] == ["worktree", "create"]:
                return {
                    "result": {
                        "workspace": {"workspace_id": "w9"},
                        "tab": {"tab_id": "w9:t1"},
                        "root_pane": {"pane_id": "w9:p1"},
                    }
                }
            return {}

        result = ensure_worktree(
            project=self.root,
            change="login",
            stream="auth",
            branch="feat/login-auth",
            runner=runner,
        )
        self.assertEqual(result["action"], "created")
        create = next(call for call in calls if call[:2] == ["worktree", "create"])
        self.assertIn("--cwd", create)
        self.assertIn("--branch", create)
        self.assertIn("--label", create)
        self.assertIn("--no-focus", create)
        self.assertEqual(result["label"], "demo / login/auth")

    def test_worktree_maps_existing_branch(self) -> None:
        init_work(self.root, "login", "large", session="s1", repo="demo")

        def runner(args: list[str]) -> dict:
            cmd = _cmd(args)
            if cmd[:2] == ["worktree", "list"]:
                return {
                    "result": {
                        "worktrees": [
                            {
                                "branch": "feat/login-auth",
                                "open_workspace_id": "w3",
                                "cwd": "C:/wt/auth",
                                "root_pane_id": "w3:p1",
                                "tab_id": "w3:t1",
                            }
                        ]
                    }
                }
            raise HerdrError("should not create", "unexpected")

        result = ensure_worktree(
            project=self.root,
            change="login",
            stream="auth",
            branch="feat/login-auth",
            runner=runner,
        )
        self.assertEqual(result["action"], "mapped")
        self.assertEqual(result["workspace_id"], "w3")


if __name__ == "__main__":
    unittest.main()
