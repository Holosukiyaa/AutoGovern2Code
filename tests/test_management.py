from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bootstrap

from ag2c.enrollment import enroll_project
from ag2c.gitops import git, head, status_entries
from ag2c.management import add_project, align_managed_projects, managed_projects, project_details, project_status, stop_managing
from ag2c.storage import configured_manifest, find_project_record, project_store

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
    def test_project_details_returns_real_governance_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "project")
            enroll_project(root, project_id="managed-project", skill_root=workspace / "skills")

            with patch("ag2c.management.harness_status", return_value=READY_AGENTS):
                details = project_details(root)

            self.assertTrue(details["available"])
            self.assertEqual("managed-project", details["manifest"]["project_id"])
            self.assertTrue(details["manifest"]["targets"])
            self.assertTrue(details["cards"])
            self.assertTrue(details["index"]["current"])
            self.assertIsNotNone(details["index"]["summary"])
            self.assertEqual([], details["worktrees"])
            self.assertGreaterEqual(details["ledger"]["events"], 1)
            self.assertIn("items", details["pending"])
            self.assertIn("pending_count", details["project"])

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
            self.assertFalse(result["uninstalled"])
            self.assertEqual("stopped", result["governance"])
            self.assertIsNone(configured_manifest(root))
            self.assertTrue(manifest.is_file())
            self.assertFalse(str(git(root, "config", "--get", "core.hooksPath", check=False)).strip())
            self.assertEqual([], status_entries(root))
            record = find_project_record(root)
            self.assertIsNotNone(record)
            self.assertEqual("stopped", record["governance"])
            listed = next(item for item in managed_projects() if item["root"] == str(root))
            self.assertEqual("stopped", listed["state"])
            self.assertFalse(any(item.get("root") == str(root) for item in align_managed_projects()))
            details = project_details(root)
            self.assertTrue(details["available"])
            self.assertTrue(details["cards"])
            from ag2c.tasks import evidence

            report = evidence(root, verify_local=False)
            self.assertEqual("managed-project", report["project"])
            self.assertFalse(report["managed"])
            self.assertTrue(report["ledger_valid"])
            resumed = add_project(root)
            self.assertTrue(resumed["managed"])
            self.assertEqual("active", resumed["governance"])
            self.assertIsNotNone(configured_manifest(root))

    def test_uninstall_removes_registry_and_governance_store(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "project")
            enroll_project(root, project_id="managed-project", skill_root=workspace / "skills")
            store = project_store(root)
            self.assertTrue(store.is_dir())
            result = stop_managing(root, remove_data=True)
            self.assertTrue(result["uninstalled"])
            self.assertTrue(result["data_removed"])
            self.assertIsNone(find_project_record(root))
            self.assertFalse(store.exists())
            self.assertFalse(any(item["root"] == str(root) for item in managed_projects()))


if __name__ == "__main__":
    unittest.main()
