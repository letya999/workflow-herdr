from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bootstrap import bootstrap
from detect import detect
from herdr_cli import HerdrError
from init_work import init_work
from layout_graph import layout_graph
from orchestrate import advance
from workflow_guard import doctor, validate
from yaml_lite import dump_yaml


def _cmd(args: list[str]) -> list[str]:
    if len(args) >= 2 and args[0] in ("--session", "--machine"):
        return args[2:]
    return args


class FakeHerdr:
    def __init__(self, cwd: str) -> None:
        self.cwd = cwd
        self.calls: list[list[str]] = []
        self.n = 1
        self.agents: list[dict] = []
        self.closed: list[str] = []

    def __call__(self, args: list[str]) -> dict:
        cmd = _cmd(args)
        self.calls.append(cmd)
        if cmd[:2] == ["pane", "current"]:
            return {"pane_id": "w1:p1"}
        if cmd[:2] == ["pane", "split"]:
            self.n += 1
            return {"result": {"pane": {"pane_id": f"w1:p{self.n}"}}}
        if cmd[:2] == ["agent", "list"]:
            return {"result": {"agents": self.agents}}
        if cmd[:2] == ["agent", "start"]:
            name = cmd[2]
            pane = cmd[cmd.index("--pane") + 1]
            self.agents.append({"name": name, "pane_id": pane, "workspace_id": "w1"})
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
        if cmd[:2] == ["pane", "close"]:
            self.closed.append(cmd[2])
            return {"ok": True}
        if cmd[:2] == ["workspace", "get"]:
            return {"result": {"cwd": self.cwd}}
        if cmd[:2] == ["worktree", "list"]:
            return {"result": {"worktrees": []}}
        if cmd[:2] == ["worktree", "create"]:
            self.n += 1
            workspace = f"w{self.n}"
            return {
                "result": {
                    "workspace": {"workspace_id": workspace, "cwd": self.cwd},
                    "tab": {"tab_id": f"{workspace}:t1"},
                    "root_pane": {"pane_id": f"{workspace}:p1"},
                }
            }
        if cmd[:2] == ["workspace", "rename"]:
            return {"ok": True}
        raise HerdrError(f"unexpected {cmd}", "unexpected")


INVENTORIES = {
    "codex": {
        "ids": ["gpt-5.6-luna"],
        "aliases": [],
        "efforts_live": ["high", "max"],
        "health": "ok",
    },
    "devin": {
        "ids": ["swe-2-high", "swe-2-max"],
        "aliases": ["swe", "swe-2"],
        "efforts_live": ["low", "medium", "high", "max"],
        "health": "ok",
    },
}

KINDS = ["codex", "devin", "grok"]
PROTOCOL = {
    "ok": True,
    "errors": [],
    "client_protocol": 22,
    "server_protocol": 22,
    "restart_needed": False,
}


class FakeHerdrE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.index = self.root / "index.yaml"
        os.environ["WORKFLOW_HERDR_INDEX"] = str(self.index)
        os.environ["WORKFLOW_HERDR_PROBE_CACHE"] = str(self.root / "probe-cache.json")
        self.addCleanup(self.tmp.cleanup)
        adr = self.root / "docs" / "adr"
        adr.mkdir(parents=True)
        (adr / "0001-auth.md").write_text(
            "---\nstatus: accepted\n---\n# Use session cookies\n",
            encoding="utf-8",
        )

    def _confirm_detection(self, graph: str = "medium") -> None:
        path = self.root / ".herdr" / "detection.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            dump_yaml(
                {
                    "systems": {
                        "requirements": {"sot": "Not used", "confidence": "high", "state": None},
                        "adr": {"sot": "docs/adr", "confidence": "high", "state": "accepted"},
                        "plans": {"sot": "Not used", "confidence": "high", "state": None},
                        "state": {"sot": "Not used", "confidence": "high", "state": None},
                    },
                    "open_design_decisions": False,
                    "independent_workstreams": 1,
                    "sizing_graph": graph,
                    "sizing_reason": "one login story",
                }
            ),
            encoding="utf-8",
        )

    def test_medium_bootstrap_to_task_ready(self) -> None:
        env = {"HERDR_ENV": "1", "HERDR_SESSION": "default"}
        with mock.patch("workflow_guard.resolve_command", return_value="C:/herdr.exe"):
            boot = bootstrap(
                self.root,
                env=env,
                inventories=INVENTORIES,
                kinds=KINDS,
                protocol=PROTOCOL,
            )
        self.assertTrue(boot["ok"], boot["errors"])
        self.assertIn("sizing_graph missing", boot["detect"]["gaps"])
        self.assertEqual(boot["detect"]["draft"]["action"], "wrote")
        self.assertEqual(
            boot["detect"]["classified"]["systems"]["adr"]["sot"], "docs/adr"
        )

        self._confirm_detection()
        found = detect(self.root)
        self.assertTrue(found["ok"], found["gaps"])
        self.assertEqual(found["classified"]["sizing_graph"], "medium")

        init_work(
            self.root,
            "login",
            "medium",
            session="default",
            tab="w1:t1",
            workspace="w1",
            env=env,
        )
        fake = FakeHerdr(str(self.root.resolve()))
        with mock.patch("workflow_guard.resolve_command", return_value="C:/herdr.exe"):
            health = doctor(
                self.root,
                "login",
                volume="medium",
                env=env,
                runner=fake,
                live=True,
                inventories=INVENTORIES,
                kinds=KINDS,
                protocol=PROTOCOL,
            )
        self.assertTrue(health["ok"], health["errors"])

        layout = layout_graph(
            project=self.root,
            change="login",
            volume="medium",
            current_pane="w1:p1",
            runner=fake,
            sleep=lambda _: None,
        )
        self.assertTrue(layout["ok"])
        self.assertEqual(len(layout["seats"]), 3)
        starts = [call for call in fake.calls if call[:2] == ["agent", "start"]]
        kinds = [call[call.index("--kind") + 1] for call in starts]
        self.assertEqual(kinds, ["codex", "devin", "devin"])

        handoff = advance(self.root, "login", "brain", "goal_created")
        self.assertEqual(handoff["to"], ["orchestrator"])
        self.assertFalse(handoff["may_wait"])
        self.assertFalse(handoff["brain_waits"])
        ready = advance(self.root, "login", "orchestrator", "task_ready")
        self.assertEqual(ready["to"], ["dispatcher"])
        self.assertTrue(ready["may_wait"])

        checked = validate(self.root, "login", env=env)
        self.assertTrue(checked["ok"], checked["errors"])
        self.assertEqual(checked["orchestration"], "dispatcher")
