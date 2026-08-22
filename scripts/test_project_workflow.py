from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from load_config import expand_layout, resolve, skill_dir


class ProjectWorkflowTests(unittest.TestCase):
    def test_default_layout_keeps_herdr_state_out_of_project_workflow(self) -> None:
        config = resolve(None)
        paths = expand_layout(config, change="change-1", task="task-1")
        self.assertEqual(paths["manifest"], ".herdr/workflow.yaml")
        self.assertEqual(paths["profile"], ".herdr/project.md")
        self.assertEqual(paths["change_dir"], ".herdr/runs/change-1")
        self.assertEqual(paths["session"], ".herdr/runs/change-1/run.json")
        self.assertNotIn("discovery", config)
        for volume in config["volumes"].values():
            self.assertNotIn("spec", volume)
            self.assertNotIn("adr", volume)
            self.assertNotIn("plan_file", volume)

    def test_project_manifest_merges_mappings_and_replaces_lists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / ".herdr" / "workflow.yaml"
            manifest.parent.mkdir()
            manifest.write_text(
                "roles:\n"
                "  worker:\n"
                "    model: project-worker\n"
                "volumes:\n"
                "  medium:\n"
                "    seats: [brain, worker]\n",
                encoding="utf-8",
            )
            config = resolve(root)
            self.assertEqual(config["roles"]["worker"]["model"], "project-worker")
            self.assertEqual(config["roles"]["worker"]["cli"], "grok")
            self.assertEqual(config["volumes"]["medium"]["seats"], ["brain", "worker"])
            self.assertIn("sequence", config["volumes"]["medium"])

    def test_init_work_creates_only_local_herdr_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git" / "info").mkdir(parents=True)
            proc = subprocess.run(
                [
                    sys.executable,
                    str(skill_dir() / "scripts" / "init_work.py"),
                    "--project",
                    str(root),
                    "--change",
                    "change-1",
                    "--volume",
                    "medium",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            change = root / ".herdr" / "runs" / "change-1"
            self.assertTrue((change / "state.yaml").is_file())
            self.assertTrue((change / "receipts").is_dir())
            run = json.loads((change / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(run["change"], "change-1")
            self.assertEqual(run["volume"], "medium")
            self.assertFalse((root / ".work").exists())
            self.assertFalse((root / ".gitignore").exists())
            self.assertEqual(
                (root / ".git" / "info" / "exclude").read_text(encoding="utf-8"),
                "/.herdr/\n",
            )

    def test_project_profile_template_keeps_required_workflow_sections(self) -> None:
        template = (skill_dir() / "references" / "project-workflow.md").read_text(
            encoding="utf-8"
        )
        for section in (
            "## Requirements",
            "## Architecture Decisions",
            "## Plans and Work Decomposition",
            "## Project State",
            "## End-to-End Workflow",
            "## Task Routing",
            "## Herdr Rules",
        ):
            self.assertIn(section, template)
        for subsection in (
            "### System",
            "### Structure",
            "### Lifecycle",
            "### Storage",
            "### Templates and examples",
            "### Tooling",
            "### Rules",
        ):
            self.assertGreaterEqual(template.count(subsection), 4)


if __name__ == "__main__":
    unittest.main()
