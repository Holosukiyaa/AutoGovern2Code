from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bootstrap

from ag2c.enrollment import enroll_project
from ag2c.errors import AG2CError
from ag2c.gitops import git
from ag2c.receipts import verify_commit_receipt
from ag2c.tasks import finish_task, start_task, verify_task

from support import git_project


class PortableReceiptTests(unittest.TestCase):
    def test_receipt_survives_prior_task_commit_and_reruns_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "项目 with spaces")
            enroll_project(root, project_id="portable-project", skill_root=workspace / "skills")
            task = start_task(
                root,
                goal="add a portable note",
                path_specs=["app:NOTE.md"],
                contract_specs=[],
                task_id="portable-note",
                worktree_root=workspace / "worktrees",
            )
            worktree = Path(task["worktree"]["path"])
            (worktree / "NOTE.md").write_text("portable proof\n", encoding="utf-8")
            git(worktree, "add", "NOTE.md")
            git(worktree, "commit", "-m", "docs: checkpoint note")
            self.assertTrue(verify_task(worktree)["passed"])

            completed = finish_task(root, "portable-note", message="docs: add portable note")
            receipt_path = root / completed["result"]["receipt_path"]
            self.assertTrue(receipt_path.is_file())
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual("ag2c.receipt.v1", receipt["schema"])
            self.assertEqual(["NOTE.md"], receipt["changed_paths"])
            report = verify_commit_receipt(root, completed["result"]["commit"], rerun=True)
            self.assertEqual("valid", report["portable_receipt"])
            self.assertEqual("passed", report["rerun"])

    def test_tampered_receipt_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "project")
            enroll_project(root, project_id="tamper-project", skill_root=workspace / "skills")
            task = start_task(
                root,
                goal="add a note",
                path_specs=["app:NOTE.md"],
                contract_specs=[],
                task_id="tamper-note",
                worktree_root=workspace / "worktrees",
            )
            worktree = Path(task["worktree"]["path"])
            (worktree / "NOTE.md").write_text("proof\n", encoding="utf-8")
            self.assertTrue(verify_task(worktree)["passed"])
            completed = finish_task(root, "tamper-note", message="docs: add note")
            receipt_path = root / completed["result"]["receipt_path"]
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["goal"] = "forged goal"
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            git(root, "add", str(receipt_path.relative_to(root)))
            git(root, "-c", "core.hooksPath=", "commit", "-m", "tamper receipt")

            with self.assertRaisesRegex(AG2CError, "receipt digest mismatch"):
                verify_commit_receipt(root)

    def test_ci_rerun_rejects_a_checker_that_mutates_governed_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "project")
            enroll_project(root, project_id="mutating-check-project", skill_root=workspace / "skills")
            task = start_task(
                root,
                goal="add a note",
                path_specs=["app:NOTE.md"],
                contract_specs=[],
                task_id="mutating-check-note",
                worktree_root=workspace / "worktrees",
            )
            worktree = Path(task["worktree"]["path"])
            (worktree / "NOTE.md").write_text("verified\n", encoding="utf-8")
            self.assertTrue(verify_task(worktree)["passed"])
            finish_task(root, "mutating-check-note", message="docs: add note")

            def mutating_check(*args, **kwargs):
                (root / "NOTE.md").write_text("changed by checker\n", encoding="utf-8")
                return {"results": [{"status": "passed"}]}

            with patch("ag2c.receipts.run_checks", side_effect=mutating_check):
                with self.assertRaisesRegex(AG2CError, "checker changed the governed bytes"):
                    verify_commit_receipt(root, rerun=True)
