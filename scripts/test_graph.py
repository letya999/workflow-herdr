from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from load_config import (
    agent_name,
    brief_path,
    constrain_agent_name,
    graph_of,
    may_wait,
    native_args,
    next_nodes,
    node_of,
    resolve,
    validate_graph,
    wait_timeout_ms,
)
from yaml_lite import load_yaml


class GraphTests(unittest.TestCase):
    def test_default_models_are_unchanged(self) -> None:
        config = resolve(None)
        orch = node_of(config, "orchestrator")
        disp = node_of(config, "dispatcher")
        worker = node_of(config, "worker")
        self.assertEqual(orch["harness"], "codex")
        self.assertEqual(orch["model"], "gpt-5.6-luna")
        self.assertEqual(orch["effort"], "max")
        self.assertEqual(disp["harness"], "devin")
        self.assertEqual(disp["model"], "swe-2-high")
        self.assertEqual(disp["effort"], "high")
        self.assertEqual(worker["harness"], "devin")
        self.assertEqual(worker["model"], "swe-2-high")
        self.assertEqual(worker["effort"], "high")
        self.assertEqual(native_args(config, "worker", 1, "x"), ["--model", "swe-2-high", "--"])
        self.assertEqual(wait_timeout_ms(config, "worker"), 1200000)
        self.assertEqual(wait_timeout_ms(config, "dispatcher"), 1200000)
        self.assertEqual(wait_timeout_ms(config, "orchestrator"), 120000)
        for seat in ("orchestrator", "dispatcher", "worker"):
            path = brief_path(config, seat)
            self.assertIsNotNone(path, seat)
            self.assertTrue(path.is_file(), seat)

    def test_workflow_yaml_transitions_parse_as_block_maps(self) -> None:
        text = (Path(__file__).resolve().parent.parent / "workflow.yaml").read_text(
            encoding="utf-8"
        )
        data = load_yaml(text)
        medium = data["graphs"]["medium"]["transitions"]
        self.assertTrue(medium)
        self.assertIsInstance(medium[0], dict)
        self.assertIn("from", medium[0])
        self.assertIn("to", medium[0])
        self.assertIn("on", medium[0])

    def test_medium_bodw_loops_exist(self) -> None:
        graph = graph_of(resolve(None), "medium")
        self.assertEqual(next_nodes(graph, "brain", "goal_created"), ["orchestrator"])
        self.assertEqual(next_nodes(graph, "orchestrator", "task_ready"), ["dispatcher"])
        self.assertEqual(next_nodes(graph, "dispatcher", "assigned"), ["worker"])
        self.assertEqual(next_nodes(graph, "worker", "progress"), ["dispatcher"])
        self.assertEqual(next_nodes(graph, "worker", "completed"), ["dispatcher"])
        self.assertEqual(next_nodes(graph, "dispatcher", "correction"), ["worker"])
        self.assertEqual(next_nodes(graph, "dispatcher", "accepted"), ["orchestrator"])
        self.assertEqual(next_nodes(graph, "orchestrator", "next_task"), ["dispatcher"])
        self.assertEqual(next_nodes(graph, "orchestrator", "plan_closed"), ["brain"])
        self.assertEqual(next_nodes(graph, "brain", "goal_ready"), [])
        self.assertFalse(next_nodes(graph, "brain", "assigned"))

    def test_medium_must_not_hand_worker_to_brain(self) -> None:
        config = resolve(None)
        self.assertEqual(validate_graph(config, "medium"), [])
        self.assertEqual(validate_graph(config, "large"), [])
        self.assertEqual(validate_graph(config, "small"), [])
        self.assertEqual(next_nodes(graph_of(config, "medium"), "brain", "done"), [])

    def test_brain_never_waits(self) -> None:
        config = resolve(None)
        self.assertFalse(may_wait(config, "brain"))
        self.assertTrue(may_wait(config, "orchestrator"))
        self.assertTrue(may_wait(config, "dispatcher"))
        self.assertTrue(may_wait(config, "worker"))

    def test_agent_names_include_change_and_fit_herdr(self) -> None:
        config = resolve(None)
        self.assertEqual(agent_name(config, "orchestrator", 1, "login"), "login-orch")
        self.assertEqual(agent_name(config, "dispatcher", 2, "login"), "login-disp-2")
        self.assertEqual(agent_name(config, "worker", 1, "login"), "login-w-1")
        self.assertIsNone(agent_name(config, "brain", 1, "login"))
        long_name = constrain_agent_name("x" * 40, "seed")
        self.assertLessEqual(len(long_name), 32)
        self.assertRegex(long_name, r"^[a-z][a-z0-9_-]{0,31}$")

    def test_unknown_graph_is_reported(self) -> None:
        errors = validate_graph(resolve(None), "tiny")
        self.assertEqual(errors, ["unknown graph: tiny"])

    def test_nodes_overlay_changes_harness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / ".herdr" / "workflow.yaml"
            manifest.parent.mkdir()
            manifest.write_text(
                "nodes:\n"
                "  worker:\n"
                "    harness: grok\n"
                "    model: grok-4.6\n"
                "    effort: high\n",
                encoding="utf-8",
            )
            config = resolve(root)
            self.assertEqual(node_of(config, "worker")["harness"], "grok")
            self.assertEqual(node_of(config, "worker")["model"], "grok-4.6")
            self.assertEqual(node_of(config, "orchestrator")["model"], "gpt-5.6-luna")


if __name__ == "__main__":
    unittest.main()
