from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from herdr_cli import (
    HerdrError,
    is_plain_output_command,
    screen_text,
    session_argv,
    subprocess_runner,
)
from init_work import init_work
from start_seat import ensure_seat_ready, looks_like_trust, start_seat


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
        self.start_errors: list[HerdrError] = []
        self.prompt_errors: list[HerdrError] = []
        self.send_key_errors: list[HerdrError] = []
        self.closed: list[str] = []
        self.screens: list[str] | str = COMPOSER_SCREEN
        self.keys: list[list[str]] = []

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
        if cmd[:2] == ["agent", "focus"]:
            return {"ok": True}
        if cmd[:2] == ["agent", "start"]:
            if self.start_errors:
                raise self.start_errors.pop(0)
            self.agents.append(
                {"name": cmd[2], "pane_id": cmd[cmd.index("--pane") + 1]}
            )
            return {"ok": True}
        if cmd[:2] == ["agent", "read"]:
            return {"text": self._screen()}
        if cmd[:2] == ["agent", "send-keys"]:
            if self.send_key_errors:
                raise self.send_key_errors.pop(0)
            self.keys.append(cmd[2:])
            if isinstance(self.screens, str) and looks_like_trust(self.screens):
                self.screens = COMPOSER_SCREEN
            return {"ok": True}
        if cmd[:2] == ["agent", "prompt"]:
            if self.prompt_errors:
                raise self.prompt_errors.pop(0)
            return {"ok": True}
        if cmd[:2] == ["pane", "close"]:
            self.closed.append(cmd[2])
            return {"ok": True}
        return {}


class StartSeatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.index = self.root / "index.yaml"
        self.addCleanup(self.tmp.cleanup)

    def _init(self, change: str = "login") -> None:
        import os

        os.environ["WORKFLOW_HERDR_INDEX"] = str(self.index)
        init_work(self.root, change, "medium", session="default")

    def test_focuses_live_agent(self) -> None:
        self._init()
        fake = FakeHerdr()
        fake.agents = [{"name": "login-orch", "pane_id": "w1:p2", "workspace_id": "w1"}]
        from run_store import load_identity, save_identity

        data = load_identity(self.root, "login")
        data["workspace_id"] = "w1"
        save_identity(self.root, "login", data)
        result = start_seat(
            project=self.root,
            change="login",
            seat="orchestrator",
            pane_id="w1:p9",
            runner=fake,
            sleep=lambda _: None,
        )
        self.assertEqual(result["action"], "focused")
        self.assertEqual(result["agent"], "login-orch")
        self.assertTrue(any(call[:2] == ["agent", "focus"] for call in fake.calls))
        self.assertFalse(any(call[:2] == ["agent", "start"] for call in fake.calls))

    def test_retries_pane_busy_then_starts(self) -> None:
        self._init()
        fake = FakeHerdr()
        fake.start_errors = [HerdrError("busy", "agent_pane_busy")]
        session = self.root / ".herdr" / "runs" / "login" / "run.json"
        result = start_seat(
            project=self.root,
            change="login",
            seat="orchestrator",
            pane_id="w1:p2",
            runner=fake,
            sleep=lambda _: None,
        )
        self.assertEqual(result["action"], "started")
        starts = [call for call in fake.calls if call[:2] == ["agent", "start"]]
        self.assertEqual(len(starts), 2)
        self.assertIn("--kind", starts[-1])
        self.assertIn("codex", starts[-1])
        self.assertIn("--timeout", starts[-1])
        self.assertTrue(session.read_text(encoding="utf-8"))

    def test_rolls_back_pane_if_start_never_succeeds(self) -> None:
        self._init()
        fake = FakeHerdr()
        fake.start_errors = [HerdrError("busy", "agent_pane_busy") for _ in range(8)]
        with self.assertRaises(HerdrError):
            start_seat(
                project=self.root,
                change="login",
                seat="orchestrator",
                pane_id="w1:p2",
                runner=fake,
                sleep=lambda _: None,
            )
        self.assertEqual(fake.closed, ["w1:p2"])

    def test_passes_brief_as_start_prompt(self) -> None:
        self._init()
        fake = FakeHerdr()
        result = start_seat(
            project=self.root,
            change="login",
            seat="dispatcher",
            number=1,
            pane_id="w1:p3",
            runner=fake,
            sleep=lambda _: None,
        )
        self.assertEqual(result["action"], "started")
        self.assertTrue(result["briefed"])
        starts = [_cmd(call) for call in fake.calls if _cmd(call)[:2] == ["agent", "start"]]
        self.assertTrue(starts)
        self.assertIn("--", starts[-1])
        brief_arg = next(part for part in starts[-1] if "You are Dispatcher" in part)
        self.assertNotIn("\n", brief_arg)
        self.assertNotIn("'", brief_arg)
        brief_index = starts[-1].index(brief_arg)
        self.assertEqual(starts[-1][brief_index - 3:brief_index], ["--model", "swe-2-high", "--"])
        self.assertTrue((self.root / ".herdr" / "runs" / "login" / "briefs" / "dispatcher.md").is_file())
        self.assertFalse(any(_cmd(call)[:2] == ["agent", "prompt"] for call in fake.calls))
        self.assertEqual(fake.closed, [])
        self.assertTrue(result["trust_cleared"])
        self.assertFalse(result["trust_sent_enter"])

    def test_project_brief_overlay_wins(self) -> None:
        self._init()
        overlay = self.root / ".herdr"
        overlay.mkdir(parents=True, exist_ok=True)
        (overlay / "worker.md").write_text("# Worker\nProject-only worker brief.\n", encoding="utf-8")
        (overlay / "workflow.yaml").write_text(
            "nodes:\n  worker:\n    brief: .herdr/worker.md\n",
            encoding="utf-8",
        )
        fake = FakeHerdr()
        result = start_seat(
            project=self.root,
            change="login",
            seat="worker",
            number=1,
            pane_id="w1:p4",
            runner=fake,
            sleep=lambda _: None,
        )
        self.assertTrue(result["briefed"])
        starts = [_cmd(call) for call in fake.calls if _cmd(call)[:2] == ["agent", "start"]]
        self.assertTrue(any("Project-only worker brief" in part for part in starts[-1]))
        self.assertFalse(any(_cmd(call)[:2] == ["agent", "prompt"] for call in fake.calls))
        self.assertFalse(any(_cmd(call)[:2] == ["agent", "send-keys"] for call in fake.calls))

    def test_dismisses_codex_trust_dialog_with_enter(self) -> None:
        self._init()
        fake = FakeHerdr()
        fake.screens = [TRUST_SCREEN, COMPOSER_SCREEN]
        result = start_seat(
            project=self.root,
            change="login",
            seat="orchestrator",
            pane_id="w1:p2",
            runner=fake,
            sleep=lambda _: None,
        )
        self.assertEqual(result["action"], "started")
        self.assertTrue(result["trust_cleared"])
        self.assertTrue(result["trust_sent_enter"])
        keys = [_cmd(call) for call in fake.calls if _cmd(call)[:2] == ["agent", "send-keys"]]
        self.assertEqual(keys, [["agent", "send-keys", "login-orch", "enter"]])
        self.assertFalse(any(_cmd(call)[:2] == ["agent", "prompt"] for call in fake.calls))
        self.assertEqual(fake.closed, [])

    def test_skips_trust_dismiss_for_devin(self) -> None:
        self._init()
        fake = FakeHerdr()
        fake.screens = [TRUST_SCREEN]
        result = start_seat(
            project=self.root,
            change="login",
            seat="worker",
            number=1,
            pane_id="w1:p4",
            runner=fake,
            sleep=lambda _: None,
        )
        self.assertEqual(result["kind"], "devin")
        self.assertTrue(result["trust_cleared"])
        self.assertFalse(result["trust_sent_enter"])
        self.assertFalse(any(_cmd(call)[:2] == ["agent", "read"] for call in fake.calls))
        self.assertFalse(any(_cmd(call)[:2] == ["agent", "send-keys"] for call in fake.calls))

    def test_trust_send_keys_failure_does_not_rollback(self) -> None:
        self._init()
        fake = FakeHerdr()
        fake.screens = TRUST_SCREEN
        fake.send_key_errors = [HerdrError("no keys", "send_failed") for _ in range(8)]
        from load_config import resolve

        config = resolve(self.root)
        config.setdefault("watch", {})["trust_timeout_ms"] = 1
        result = start_seat(
            project=self.root,
            change="login",
            seat="orchestrator",
            pane_id="w1:p2",
            runner=fake,
            sleep=lambda _: None,
            config=config,
        )
        self.assertEqual(result["action"], "started")
        self.assertFalse(result["trust_cleared"])
        self.assertEqual(result["trust_error"], "trust_dialog_still_visible")
        self.assertEqual(fake.closed, [])
        self.assertFalse(any(_cmd(call)[:2] == ["agent", "prompt"] for call in fake.calls))

    def test_ensure_ready_dismisses_live_trust(self) -> None:
        self._init()
        fake = FakeHerdr()
        fake.agents = [{"name": "login-orch", "pane_id": "w1:p2", "workspace_id": "w1"}]
        fake.screens = [TRUST_SCREEN, COMPOSER_SCREEN]
        from run_store import load_identity, save_identity

        data = load_identity(self.root, "login")
        data["workspace_id"] = "w1"
        save_identity(self.root, "login", data)
        result = ensure_seat_ready(
            project=self.root,
            change="login",
            seat="orchestrator",
            runner=fake,
            sleep=lambda _: None,
        )
        self.assertEqual(result["action"], "ready")
        self.assertTrue(result["trust_sent_enter"])
        self.assertFalse(any(_cmd(call)[:2] == ["agent", "start"] for call in fake.calls))
        self.assertFalse(any(_cmd(call)[:2] == ["agent", "prompt"] for call in fake.calls))
        self.assertFalse(any(_cmd(call)[:2] == ["agent", "focus"] for call in fake.calls))

    def test_screen_helpers(self) -> None:
        self.assertTrue(looks_like_trust(TRUST_SCREEN))
        self.assertFalse(looks_like_trust(COMPOSER_SCREEN))
        self.assertTrue(is_plain_output_command(["agent", "read", "x"]))
        self.assertTrue(is_plain_output_command(["--session", "default", "pane", "read", "w1:p1"]))
        self.assertFalse(is_plain_output_command(["agent", "prompt", "x", "hi"]))
        self.assertIn("trust", screen_text({"text": "trust"}))
        self.assertEqual(screen_text({"result": {"text": "Ask Codex to do anything"}}), "Ask Codex to do anything")

    def test_empty_herdr_session_is_stripped(self) -> None:
        runner = subprocess_runner({"HERDR_SESSION": "", "PATH": "C:\\bin"})
        self.assertIsNotNone(runner)

    def test_session_argv_never_mixes_machine_and_session(self) -> None:
        self.assertEqual(session_argv("team", "remote-1"), ["--machine", "remote-1"])
        self.assertEqual(session_argv("team", "local"), ["--session", "team"])
        self.assertEqual(session_argv("default", None), [])
        self.assertEqual(session_argv("", None), [])


if __name__ == "__main__":
    unittest.main()
