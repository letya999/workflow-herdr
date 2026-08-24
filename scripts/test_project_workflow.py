from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from load_config import expand_layout, resolve, skill_dir
from record_pane import record_pane


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

    def test_record_pane_upserts_resource_and_role(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session_file = Path(directory) / "run.json"
            session_file.write_text(
                json.dumps({"created": {"panes": []}, "roles": {}}),
                encoding="utf-8",
            )
            record_pane(
                session_file,
                pane_id="w1:p2",
                seat="orchestrator",
                number=1,
                status="created",
            )
            record_pane(
                session_file,
                pane_id="w1:p2",
                seat="orchestrator",
                number=1,
                status="failed",
                error="startup failed",
            )
            run = json.loads(session_file.read_text(encoding="utf-8"))
            self.assertEqual(
                run["created"]["panes"],
                [
                    {
                        "pane_id": "w1:p2",
                        "seat": "orchestrator",
                        "number": 1,
                        "status": "failed",
                        "error": "startup failed",
                    }
                ],
            )
            self.assertEqual(run["roles"]["orchestrator"]["pane_id"], "w1:p2")
            self.assertEqual(run["workspace_id"], "w1")

    def test_record_pane_upserts_numbered_worker_role(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session_file = Path(directory) / "run.json"
            session_file.write_text(
                json.dumps({"created": {"panes": []}, "roles": {}}),
                encoding="utf-8",
            )
            for status in ("created", "running"):
                record_pane(
                    session_file,
                    pane_id="w1:p3",
                    seat="worker",
                    number=2,
                    status=status,
                )
            run = json.loads(session_file.read_text(encoding="utf-8"))
            self.assertEqual(len(run["created"]["panes"]), 1)
            self.assertEqual(run["created"]["panes"][0]["status"], "running")
            self.assertEqual(
                run["roles"]["workers"],
                [{"pane_id": "w1:p3", "agent": "worker-2"}],
            )

    def test_record_pane_rejects_a_different_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session_file = Path(directory) / "run.json"
            session_file.write_text(
                json.dumps({"workspace_id": "w1", "created": {"panes": []}}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "belongs to w2, not w1"):
                record_pane(
                    session_file,
                    pane_id="w2:p1",
                    seat="worker",
                    number=1,
                    status="created",
                )

    def test_public_project_docs_define_release_and_security_policy(self) -> None:
        root = skill_dir()
        license_text = (root / "LICENSE").read_text(encoding="utf-8")
        contributing = (root / "CONTRIBUTING.md").read_text(encoding="utf-8")
        security = (root / "SECURITY.md").read_text(encoding="utf-8")
        readme = (root / "README.md").read_text(encoding="utf-8")
        self.assertIn("MIT License", license_text)
        self.assertIn("feature branch -> dev -> main", contributing)
        self.assertIn("private GitHub security advisory", security)
        for link in ("LICENSE", "CONTRIBUTING.md", "SECURITY.md"):
            self.assertIn(link, readme)


if __name__ == "__main__":
    unittest.main()
