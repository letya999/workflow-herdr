from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from herdr_cli import HerdrError
from init_work import init_work
from prompt_seat import prompt_seat
from start_seat import looks_like_trust


def _cmd(args: list[str]) -> list[str]:
    if len(args) >= 2 and args[0] in ("--session", "--machine"):
        return args[2:]
    return args


TRUST_SCREEN = (
    "Do you trust the contents of this directory?\n"
    "1. Yes, continue\n"
    "2. No, quit\n"
)
COMPOSER_SCREEN = "Ask Codex to do anything\n"


class FakeHerdr:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.agents: list[dict] = []
        self.prompt_errors: list[HerdrError] = []
        self.screens: list[str] | str = COMPOSER_SCREEN

    def _screen(self) -> str:
        if isinstance(self.screens, list):
            if self.screens:
                return self.screens.pop(0)
            return COMPOSER_SCREEN
        return self.screens

    def __call__(self, args: list[str]) -> dict:
        self.calls.append(list(args))
        cmd = _cmd(args)
        if cmd[:2] == ["agent", "list"]:
            return {"result": {"agents": self.agents}}
        if cmd[:2] == ["agent", "get"]:
            name = cmd[2]
            agent = next((item for item in self.agents if item.get("name") == name), None)
            if not agent:
                raise HerdrError("missing", "agent_not_found")
            return {
                "result": {
                    "agent": {
                        "name": name,
                        "agent": agent.get("kind") or "codex",
                        "agent_status": agent.get("status") or "idle",
                        "pane_id": agent.get("pane_id"),
                        "terminal_title": agent.get("title") or "Ask Codex to do anything",
                        "terminal_title_stripped": agent.get("title")
                        or "Ask Codex to do anything",
                    }
                }
            }
        if cmd[:2] == ["agent", "read"]:
            return {"text": self._screen()}
        if cmd[:2] == ["agent", "send-keys"]:
            if isinstance(self.screens, str) and looks_like_trust(self.screens):
                self.screens = COMPOSER_SCREEN
            return {"ok": True}
        if cmd[:2] == ["agent", "prompt"]:
            if self.prompt_errors:
                raise self.prompt_errors.pop(0)
            return {"ok": True}
        return {}


class PromptSeatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        import os

        os.environ["WORKFLOW_HERDR_INDEX"] = str(self.root / "index.yaml")
        init_work(self.root, "login", "medium", session="default", workspace="w1")

    def test_brain_handoff_does_not_wait_and_skips_trust(self) -> None:
        fake = FakeHerdr()
        fake.agents = [
            {
                "name": "login-orch",
                "pane_id": "w1:p2",
                "workspace_id": "w1",
                "kind": "codex",
                "status": "idle",
            }
        ]
        fake.screens = [TRUST_SCREEN, COMPOSER_SCREEN, COMPOSER_SCREEN]
        result = prompt_seat(
            project=self.root,
            change="login",
            seat="orchestrator",
            text="Write the plan.",
            source="brain",
            runner=fake,
            sleep=lambda _: None,
        )
        self.assertTrue(result["prompted"])
        self.assertFalse(result["waited"])
        self.assertTrue(result["trust_sent_enter"])
        prompts = [_cmd(call) for call in fake.calls if _cmd(call)[:2] == ["agent", "prompt"]]
        self.assertEqual(len(prompts), 1)
        self.assertNotIn("--wait", prompts[0])
        self.assertIn("Write the plan.", prompts[0])

    def test_dispatcher_waits_on_worker_and_timeout_is_not_death(self) -> None:
        fake = FakeHerdr()
        fake.agents = [
            {
                "name": "login-w-1",
                "pane_id": "w1:p4",
                "workspace_id": "w1",
                "kind": "devin",
                "status": "working",
            }
        ]
        fake.prompt_errors = [HerdrError("timed out waiting for agent status", "timeout")]
        result = prompt_seat(
            project=self.root,
            change="login",
            seat="worker",
            number=1,
            text="Do t1.",
            source="dispatcher",
            runner=fake,
            sleep=lambda _: None,
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["timeout"])
        self.assertTrue(result["agent_alive"])
        self.assertTrue(result["waited"])
        prompts = [_cmd(call) for call in fake.calls if _cmd(call)[:2] == ["agent", "prompt"]]
        self.assertIn("--wait", prompts[0])
        self.assertIn("--timeout", prompts[0])
        self.assertEqual(prompts[0][prompts[0].index("--timeout") + 1], "1200000")

    def test_refuses_to_prompt_a_shell(self) -> None:
        fake = FakeHerdr()
        fake.agents = [
            {
                "name": "login-orch",
                "pane_id": "w1:p2",
                "workspace_id": "w1",
                "kind": "codex",
                "title": "pwsh.exe",
            }
        ]
        with self.assertRaises(HerdrError) as raised:
            prompt_seat(
                project=self.root,
                change="login",
                seat="orchestrator",
                text="hi",
                source="brain",
                runner=fake,
                sleep=lambda _: None,
            )
        self.assertEqual(raised.exception.code, "agent_exited")
        self.assertFalse(any(_cmd(call)[:2] == ["agent", "prompt"] for call in fake.calls))


if __name__ == "__main__":
    unittest.main()
