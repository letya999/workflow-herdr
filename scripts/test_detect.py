from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from detect import detect, write_draft, write_stub
from yaml_lite import dump_yaml


class DetectTests(unittest.TestCase):
    def test_reads_excerpts_and_requires_brain_classification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adr = root / "docs" / "adr"
            adr.mkdir(parents=True)
            (adr / "0001-auth.md").write_text(
                "---\nstatus: accepted\n---\n# Use session cookies\n\nAccepted.\n",
                encoding="utf-8",
            )
            result = detect(root)
            self.assertFalse(result["ok"])
            self.assertIn("detection.yaml missing", result["gaps"])
            excerpts = result["groups"]["adr"]["excerpts"]
            self.assertEqual(excerpts[0]["heuristic_state"], "accepted")
            self.assertIn("session cookies", excerpts[0]["heading"].lower())
            self.assertIn("Read every excerpt", result["brain_task"]["instruction"])

    def test_complete_detection_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_stub(root)
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
                        "sizing_graph": "medium",
                        "sizing_reason": "one login story",
                    }
                ),
                encoding="utf-8",
            )
            result = detect(root)
            self.assertTrue(result["ok"], result["gaps"])
            self.assertEqual(result["classified"]["sizing_graph"], "medium")

    def test_write_draft_fills_systems_but_does_not_size(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adr = root / "docs" / "adr"
            adr.mkdir(parents=True)
            (adr / "0001-auth.md").write_text(
                "---\nstatus: accepted\n---\n# Use session cookies\n",
                encoding="utf-8",
            )
            drafted = write_draft(root)
            self.assertEqual(drafted["action"], "wrote")
            result = detect(root)
            self.assertFalse(result["ok"])
            classified = result["classified"]
            self.assertTrue(classified.get("draft"))
            self.assertEqual(classified["systems"]["adr"]["sot"], "docs/adr")
            self.assertEqual(classified["systems"]["adr"]["confidence"], "low")
            self.assertEqual(classified["systems"]["requirements"]["sot"], "Not used")
            self.assertEqual(classified["systems"]["requirements"]["confidence"], "high")
            self.assertIn("sizing_graph missing", result["gaps"])
            self.assertIn("sizing_reason missing", result["gaps"])

    def test_write_draft_keeps_confirmed_detection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_stub(root)
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
                        "sizing_graph": "medium",
                        "sizing_reason": "one login story",
                    }
                ),
                encoding="utf-8",
            )
            drafted = write_draft(root)
            self.assertEqual(drafted["action"], "keep")
            result = detect(root)
            self.assertTrue(result["ok"], result["gaps"])
            self.assertEqual(result["classified"]["sizing_graph"], "medium")


if __name__ == "__main__":
    unittest.main()
