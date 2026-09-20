from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from herdr_cli import HerdrError
from init_work import init_work
from layout_graph import layout_graph, layout_seats_for
from load_config import graph_of, resolve


def _cmd(args: list[str]) -> list[str]:
    if len(args) >= 2 and args[0] in ("--session", "--machine"):
        return args[2:]
    return args


class FakeLayout:
    def __init__(self, cwd: str = "C:/proj") -> None:
        self.calls: list[list[str]] = []
        self.n = 1
        self.wt = 8
        self.cwd = cwd
        self.agents: list[dict] = []
        self.closed: list[str] = []
        self.fail_start = False

    def __call__(self, args: list[str]) -> dict:
        cmd = _cmd(args)
        self.calls.append(cmd)
        if cmd[:2] == ["pane", "current"]:
            return {"pane_id": "w1:p1"}
        if cmd[:2] == ["pane", "split"]:
            self.n += 1
            parent = cmd[cmd.index("--pane") + 1] if "--pane" in cmd else "w1:p1"
            workspace = parent.split(":")[0]
            return {"result": {"pane": {"pane_id": f"{workspace}:p{self.n}"}}}
        if cmd[:2] == ["agent", "list"]:
            return {"result": {"agents": self.agents}}
        if cmd[:2] == ["agent", "start"]:
            if self.fail_start:
                raise HerdrError("busy", "agent_pane_busy")
            name = cmd[2]
            pane = cmd[cmd.index("--pane") + 1]
            self.agents.append({"name": name, "pane_id": pane})
            return {"ok": True}
        if cmd[:2] == ["agent", "read"]:
            return {"text": "Ask Codex to do anything"}
        if cmd[:2] == ["agent", "send-keys"]:
            return {"ok": True}
        if cmd[:2] == ["agent", "prompt"]:
            return {"ok": True}
        if cmd[:2] == ["pane", "rename"]:
            return {"ok": True}
        if cmd[:2] == ["pane", "report-metadata"]:
            return {"ok": True}
        if cmd[:2] == ["tab", "rename"]:
            return {"ok": True}
        if cmd[:2] == ["workspace", "rename"]:
            return {"ok": True}
        if cmd[:2] == ["workspace", "get"]:
            return {"result": {"cwd": self.cwd}}
        if cmd[:2] == ["worktree", "list"]:
            return {"result": {"worktrees": []}}
        if cmd[:2] == ["worktree", "create"]:
            self.wt += 1
            workspace = f"w{self.wt}"
            branch = cmd[cmd.index("--branch") + 1]
            stream = branch.split("/")[-1]
            cwd = f"{self.cwd}/wt-{stream}"
            return {
                "result": {
                    "workspace": {"workspace_id": workspace, "cwd": cwd},
                    "tab": {"tab_id": f"{workspace}:t1"},
                    "root_pane": {"pane_id": f"{workspace}:p1"},
                }
            }
        if cmd[:2] == ["worktree", "remove"]:
            return {"ok": True}
        if cmd[:2] == ["pane", "close"]:
            self.closed.append(cmd[2])
            return {"ok": True}
        return {}


class LayoutGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        os.environ["WORKFLOW_HERDR_INDEX"] = str(self.root / "index.yaml")
        self.addCleanup(self.tmp.cleanup)

    def test_medium_layout_lists_dispatcher_before_worker(self) -> None:
        seats = layout_seats_for(graph_of(resolve(None), "medium"))
        self.assertEqual(seats, ["orchestrator", "dispatcher", "worker"])

    def test_creates_three_panes_and_starts_kinds(self) -> None:
        init_work(self.root, "login", "medium", session="default", tab="w1:t1", workspace="w1")
        fake = FakeLayout()
        result = layout_graph(
            project=self.root,
            change="login",
            volume="medium",
            current_pane="w1:p1",
            runner=fake,
            sleep=lambda _: None,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["seats"]), 3)
        starts = [call for call in fake.calls if call[:2] == ["agent", "start"]]
        kinds = []
        for call in starts:
            kinds.append(call[call.index("--kind") + 1])
        self.assertEqual(kinds, ["codex", "codex", "devin"])
        starts = [call for call in fake.calls if call[:2] == ["agent", "start"]]
        self.assertTrue(any("You are Orchestrator" in part for call in starts for part in call))
        self.assertFalse(any(call[:2] == ["agent", "prompt"] for call in fake.calls))
        self.assertTrue(any(call[:2] == ["tab", "rename"] for call in fake.calls))
        self.assertFalse(fake.closed)

    def test_rolls_back_unstarted_panes(self) -> None:
        init_work(self.root, "login", "medium", session="default")
        fake = FakeLayout()
        fake.fail_start = True
        with self.assertRaises(HerdrError):
            layout_graph(
                project=self.root,
                change="login",
                current_pane="w1:p1",
                runner=fake,
                sleep=lambda _: None,
            )
        self.assertTrue(fake.closed)

    def test_large_requires_two_streams(self) -> None:
        init_work(self.root, "login", "large", session="default", tab="w1:t1", workspace="w1")
        fake = FakeLayout()
        with self.assertRaises(HerdrError) as raised:
            layout_graph(
                project=self.root,
                change="login",
                volume="large",
                current_pane="w1:p1",
                runner=fake,
                sleep=lambda _: None,
            )
        self.assertEqual(raised.exception.code, "missing_streams")
        self.assertFalse(any(call[:2] == ["worktree", "create"] for call in fake.calls))

    def test_large_starts_dispatcher_worker_pair_per_worktree(self) -> None:
        init_work(
            self.root,
            "login",
            "large",
            session="default",
            tab="w1:t1",
            workspace="w1",
            streams=["auth", "billing"],
        )
        fake = FakeLayout(cwd=str(self.root))
        result = layout_graph(
            project=self.root,
            change="login",
            volume="large",
            current_pane="w1:p1",
            runner=fake,
            sleep=lambda _: None,
        )
        self.assertTrue(result["ok"])
        starts = [call for call in fake.calls if call[:2] == ["agent", "start"]]
        names = [call[2] for call in starts]
        self.assertEqual(
            names,
            ["login-orch", "login-disp-1", "login-w-1", "login-disp-2", "login-w-2"],
        )
        kinds = [call[call.index("--kind") + 1] for call in starts]
        self.assertEqual(kinds, ["codex", "codex", "devin", "codex", "devin"])
        creates = [call for call in fake.calls if call[:2] == ["worktree", "create"]]
        self.assertEqual(len(creates), 2)
        self.assertTrue(any("login/auth" in call for call in creates))
        self.assertTrue(any("login/billing" in call for call in creates))
        splits = [call for call in fake.calls if call[:2] == ["pane", "split"]]
        cwd_by_pane_parent = []
        for call in splits:
            cwd = call[call.index("--cwd") + 1]
            cwd_by_pane_parent.append(cwd)
        self.assertEqual(cwd_by_pane_parent[0], str(self.root))
        self.assertTrue(any(str(self.root) + os.sep + "wt-auth" == cwd or cwd.endswith("wt-auth") for cwd in cwd_by_pane_parent))
        self.assertTrue(any(cwd.endswith("wt-billing") for cwd in cwd_by_pane_parent))
        self.assertFalse(any(call[:2] == ["agent", "prompt"] for call in fake.calls))
        self.assertEqual(len(result["seats"]), 5)


if __name__ == "__main__":
    unittest.main()
