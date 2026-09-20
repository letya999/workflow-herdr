from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from load_config import resolve
from probe import (
    herdr_protocol,
    inventory_for,
    model_matches,
    parse_codex_models_cache,
    parse_devin_models,
    parse_grok_models,
    parse_herdr_kinds,
    parse_herdr_status,
    probe_seats,
)
from workflow_guard import doctor


HELP = """
      --kind <KIND>
          [possible values: pi, claude, codex, gemini, cursor, devin, grok]
"""

DEVIN_TEXT = """
SWE-2 (swe-2)
  aliases: swe
  swe-2-high                                                               SWE-2 High
  swe-2-max                                                                SWE-2 Max
"""

GROK_TEXT = """
Available models:
  * grok-4.6 (default)
  - grok-4.5
"""


class ProbeTests(unittest.TestCase):
    def test_parse_herdr_kinds(self) -> None:
        kinds = parse_herdr_kinds(HELP)
        self.assertIn("codex", kinds)
        self.assertIn("devin", kinds)
        self.assertIn("grok", kinds)

    def test_swe2_max_matches_live_devin_id(self) -> None:
        inventory = parse_devin_models(DEVIN_TEXT)
        self.assertTrue(model_matches("swe2", inventory, "max"))
        self.assertTrue(model_matches("swe-2", inventory, "max"))
        self.assertFalse(model_matches("missing-model", inventory, "max"))

    def test_help_parser_ignores_sandbox_policies(self) -> None:
        from probe import parse_help_efforts

        text = (
            "--sandbox <POLICY>\n"
            "  [possible values: read-only, workspace-write, danger-full-access]\n"
            "--reasoning-effort <EFFORT>\n"
            "  [possible values: low, high, max]\n"
        )
        self.assertEqual(parse_help_efforts(text), ["low", "high", "max"])
        self.assertEqual(
            parse_help_efforts(
                "--sandbox <POLICY>\n  [possible values: read-only, workspace-write]\n"
            ),
            [],
        )

    def test_parse_grok_models(self) -> None:
        inventory = parse_grok_models(GROK_TEXT)
        self.assertIn("grok-4.6", inventory["ids"])
        self.assertTrue(model_matches("grok-4.6", inventory))

    def test_probe_rejects_unknown_kind_and_model(self) -> None:
        config = resolve(None)
        result = probe_seats(
            config,
            volume="medium",
            kinds=["codex"],
            inventories={
                "codex": {
                    "ids": ["gpt-5.6-luna"],
                    "aliases": [],
                    "efforts_live": ["high", "max"],
                },
                "devin": {
                    "ids": ["other-1"],
                    "aliases": [],
                    "efforts_live": ["max"],
                },
            },
        )
        self.assertFalse(result["ok"])
        self.assertTrue(any("no kind devin" in item for item in result["errors"]))
        self.assertTrue(any("model swe2 is not in devin inventory" in item for item in result["errors"]))

    def test_probe_accepts_live_inventory(self) -> None:
        config = resolve(None)
        result = probe_seats(
            config,
            volume="medium",
            kinds=["codex", "devin", "grok"],
            inventories={
                "codex": {
                    "ids": ["gpt-5.6-luna"],
                    "aliases": [],
                    "efforts_live": ["high", "max"],
                },
                "devin": {
                    "ids": ["swe-2-max"],
                    "aliases": ["swe", "swe-2"],
                    "efforts_live": ["low", "medium", "high", "max"],
                },
            },
        )
        self.assertTrue(result["ok"], result["errors"])
        self.assertTrue(result["seats"]["worker"]["model_ok"])
        self.assertTrue(result["seats"]["orchestrator"]["kind_ok"])

    def test_doctor_start_uses_live_probe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = {"HERDR_ENV": "1"}
            inventories = {
                "codex": {
                    "ids": ["gpt-5.6-luna"],
                    "aliases": [],
                    "efforts_live": ["high", "max"],
                },
                "devin": {
                    "ids": ["swe-2-max"],
                    "aliases": ["swe-2"],
                    "efforts_live": ["max"],
                },
            }
            with mock.patch("workflow_guard.resolve_command", return_value="C:/herdr.exe"):
                result = doctor(
                    root,
                    "",
                    env=env,
                    live=True,
                    inventories=inventories,
                    kinds=["codex", "devin"],
                    protocol={"ok": True, "errors": []},
                )
            self.assertTrue(result["ok"], result["errors"])
            self.assertTrue(any(item["label"] == "live harness/model/effort" for item in result["checks"]))
            self.assertTrue(any(item["label"] == "herdr protocol" for item in result["checks"]))

    def test_protocol_mismatch_is_a_hard_stop(self) -> None:
        status = (
            "client:\n"
            "  protocol: 22\n"
            "server:\n"
            "  status: running\n"
            "  private_protocol: 19\n"
            "  private_protocol_compatible: no\n"
            "  endpoint_compatible: no\n"
            "update:\n"
            "  restart_needed: yes\n"
            "  server_binary_stale: yes\n"
        )
        parsed = parse_herdr_status(status)
        self.assertFalse(parsed["ok"])
        self.assertTrue(parsed["restart_needed"])
        self.assertIn("herdr server stop", parsed["fix"])
        json_err = '{"error":{"code":"protocol_mismatch","message":"stale server"}}'
        mismatch = herdr_protocol(run_status=json_err)
        self.assertFalse(mismatch["ok"])
        self.assertTrue(any("protocol_mismatch" in item for item in mismatch["errors"]))

    def test_compatible_status_passes(self) -> None:
        status = (
            "client:\n"
            "  protocol: 22\n"
            "server:\n"
            "  status: running\n"
            "  private_protocol: 22\n"
            "  private_protocol_compatible: yes\n"
            "  endpoint_compatible: yes\n"
            "update:\n"
            "  restart_needed: no\n"
            "  server_binary_stale: no\n"
        )
        parsed = parse_herdr_status(status)
        self.assertTrue(parsed["ok"], parsed["errors"])
        self.assertFalse(parsed["restart_needed"])

    def test_codex_models_cache_skips_hidden(self) -> None:
        parsed = parse_codex_models_cache(
            {
                "fetched_at": "2026-09-20T11:43:42Z",
                "models": [
                    {
                        "slug": "gpt-5.6-luna",
                        "visibility": "list",
                        "supported_reasoning_levels": [
                            {"effort": "high"},
                            {"effort": "max"},
                            {"effort": "ultra"},
                        ],
                    },
                    {
                        "slug": "gpt-reserve",
                        "visibility": "hide",
                        "supported_reasoning_levels": [{"effort": "max"}],
                    },
                ],
            }
        )
        self.assertIn("gpt-5.6-luna", parsed["ids"])
        self.assertNotIn("gpt-reserve", parsed["ids"])
        self.assertEqual(parsed["efforts_live"], ["high", "max"])
        self.assertTrue(model_matches("gpt-5.6-luna", parsed, "max"))

    def test_inventory_uses_probe_cache(self) -> None:
        calls: list[list[str]] = []

        def fake_cli(_exe: str, args: list[str]) -> dict:
            calls.append(args)
            return {"ok": True, "text": DEVIN_TEXT, "code": 0}

        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "probe-cache.json"
            with mock.patch.dict(
                os.environ,
                {
                    "WORKFLOW_HERDR_PROBE_CACHE": str(cache),
                    "WORKFLOW_HERDR_PROBE_TTL": "900",
                    "WORKFLOW_HERDR_PROBE_FRESH": "",
                },
                clear=False,
            ):
                os.environ.pop("WORKFLOW_HERDR_PROBE_FRESH", None)
                first = inventory_for("devin", "C:/devin.exe", run_cli_fn=fake_cli)
                second = inventory_for("devin", "C:/devin.exe", run_cli_fn=fake_cli)
            self.assertEqual(len(calls), 1)
            self.assertTrue(model_matches("swe2", first, "max"))
            self.assertEqual(first["ids"], second["ids"])

    def test_shared_inventory_calls_doctor_once(self) -> None:
        calls: list[tuple[str, tuple]] = []

        def fake_cli(exe: str, args: list[str], **_kwargs) -> dict:
            calls.append((exe, tuple(args)))
            if args[:1] == ["doctor"]:
                return {"ok": True, "text": "logged in", "code": 0}
            return {"ok": True, "text": DEVIN_TEXT, "code": 0}

        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "probe-cache.json"
            with mock.patch.dict(
                os.environ,
                {"WORKFLOW_HERDR_PROBE_CACHE": str(cache), "WORKFLOW_HERDR_PROBE_TTL": "900"},
                clear=False,
            ):
                os.environ.pop("WORKFLOW_HERDR_PROBE_FRESH", None)
                config = resolve(None)
                with mock.patch("workflow_guard.resolve_command", side_effect=lambda name: name):
                    result = probe_seats(
                        config,
                        volume="medium",
                        kinds=["codex", "devin"],
                        run_cli_fn=fake_cli,
                    )
        doctor_calls = [item for item in calls if item[1][:1] == ("doctor",)]
        self.assertEqual(len(doctor_calls), 1, calls)
        self.assertTrue(result["ok"], result["errors"])

    def test_doctor_timeout_is_warning_when_models_cache_exists(self) -> None:
        def fake_cli(_exe: str, args: list[str], **_kwargs) -> dict:
            if args[:1] == ["doctor"]:
                return {"ok": False, "text": "", "error": "timed out after 90s"}
            return {"ok": True, "text": "", "code": 0}

        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "models.json"
            cache.write_text(
                json.dumps(
                    {
                        "models": [
                            {
                                "slug": "gpt-5.6-luna",
                                "visibility": "list",
                                "supported_reasoning_levels": [{"effort": "max"}, {"effort": "high"}],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.dict(
                os.environ,
                {
                    "WORKFLOW_HERDR_CODEX_CACHE": str(cache),
                    "WORKFLOW_HERDR_PROBE_CACHE": str(Path(directory) / "probe.json"),
                    "WORKFLOW_HERDR_PROBE_TTL": "0",
                },
                clear=False,
            ):
                data = inventory_for("codex", "codex", run_cli_fn=fake_cli, use_cache=False)
        self.assertEqual(data["health"], "degraded")
        self.assertTrue(model_matches("gpt-5.6-luna", data, "max"))
        self.assertIsNone(data.get("error"))

    def test_doctor_stops_on_stale_herdr_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = {"HERDR_ENV": "1"}
            inventories = {
                "codex": {"ids": ["gpt-5.6-luna"], "aliases": [], "efforts_live": ["max"]},
                "devin": {"ids": ["swe-2-max"], "aliases": ["swe-2"], "efforts_live": ["max"]},
            }
            with mock.patch("workflow_guard.resolve_command", return_value="C:/herdr.exe"):
                result = doctor(
                    root,
                    "",
                    env=env,
                    live=True,
                    inventories=inventories,
                    kinds=["codex", "devin"],
                    protocol={
                        "ok": False,
                        "errors": ["Herdr restart_needed: yes"],
                        "fix": "herdr server stop then start herdr again",
                    },
                )
            self.assertFalse(result["ok"])
            self.assertTrue(any("restart_needed" in item for item in result["errors"]))


if __name__ == "__main__":
    unittest.main()
