from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bootstrap

from ag2c.enrollment import enroll_project
from ag2c.gitops import git, head, status_entries
from ag2c.management import managed_projects, project_status, stop_managing
from ag2c.storage import configured_manifest

from support import git_project


READY_AGENTS = [
    {
        "harness": "codex",
        "detected": True,
        "executable": "codex",
        "skill_path": "skill",
        "skill_installed": True,
        "integrated": True,
        "state": "ready",
    }
]


class ManagementTests(unittest.TestCase):
    def test_project_list_reports_enforcement_without_touching_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "project")
            original_head = head(root)
            enroll_project(root, project_id="managed-project", skill_root=workspace / "skills")

            with patch("ag2c.management.harness_status", return_value=READY_AGENTS):
                status = project_status(root)
                listed = next(item for item in managed_projects() if item["root"] == str(root))

            self.assertEqual("protected", status["state"])
            self.assertTrue(status["entry_ready"])
            self.assertTrue(status["delivery_enforced"])
            self.assertEqual("protected", listed["state"])
            self.assertEqual(original_head, head(root))
            self.assertEqual([], status_entries(root))
            self.assertFalse((root / ".ag2c").exists())

    def test_stop_management_removes_only_local_binding_and_keeps_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "project")
            enroll_project(root, project_id="managed-project", skill_root=workspace / "skills")
            manifest = configured_manifest(root)
            self.assertIsNotNone(manifest)
            result = stop_managing(root)

            self.assertTrue(result["previous_evidence_kept"])
            self.assertIsNone(configured_manifest(root))
            self.assertTrue(manifest.is_file())
            self.assertFalse(str(git(root, "config", "--get", "core.hooksPath", check=False)).strip())
            self.assertEqual([], status_entries(root))


if __name__ == "__main__":
    unittest.main()
