from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import bootstrap

from ag2c.cli import main
from ag2c.config import discover_manifest, load_manifest
from ag2c.enrollment import enroll_project
from ag2c.errors import AG2CError
from ag2c.gitops import git, head
from ag2c.tasks import (
    abandon_task,
    classify_delivery,
    describe_delivery,
    evidence,
    finish_task,
    list_tasks,
    refresh_task,
    start_task,
    task_record,
    verify_task,
)

from support import git_project


class TaskLifecycleTests(unittest.TestCase):
    def test_delivery_classifies_feature_and_fix(self) -> None:
        self.assertEqual("fix", classify_delivery("fix login timeout"))
        self.assertEqual("fix", classify_delivery("修复通知发送失败"))
        self.assertEqual("feature", classify_delivery("feat: add search page"))
        self.assertEqual("feature", classify_delivery("实现课程表筛选"))
        self.assertEqual(
            {
                "request": "把搜索做出来",
                "outcome": "实现站内搜索",
                "kind": "feature",
            },
            describe_delivery(goal="把搜索做出来", outcome="实现站内搜索\n\nAG2C-Task: x"),
        )

    def enrolled(self, workspace: Path) -> Path:
        root = git_project(workspace / "project")
        enroll_project(root, project_id="lifecycle-project", skill_root=workspace / "skills")
        return root

    def start_note_task(self, root: Path, workspace: Path, task_id: str, goal: str = "add a note"):
        return start_task(
            root,
            goal=goal,
            path_specs=["app:NOTE.md"],
            contract_specs=[],
            task_id=task_id,
            worktree_root=workspace / "worktrees",
        )

    def test_verify_marks_worktree_verified_until_merge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = self.enrolled(workspace)
            task = self.start_note_task(root, workspace, "verified-note")
            worktree = Path(task["worktree"]["path"])
            (worktree / "NOTE.md").write_text("draft\n", encoding="utf-8")

            listed = list_tasks(root)
            self.assertEqual("in-progress", listed[0]["worktree"]["lifecycle"])
            self.assertEqual("active", listed[0]["state"])

            passed = verify_task(worktree)
            self.assertTrue(passed["passed"])
            self.assertEqual("verified", passed["state"])
            self.assertEqual("verified-unmerged", passed["worktree"]["lifecycle"])
            self.assertEqual("verified", task_record(root, "verified-note")["state"])

            listed = list_tasks(root)
            self.assertEqual("verified-unmerged", listed[0]["worktree"]["lifecycle"])
            completed = finish_task(root, "verified-note", message="docs: add note")
            self.assertEqual("completed", completed["state"])
            self.assertEqual(1, completed["journal_version"])
            self.assertEqual("docs: add note", completed["delivery"]["outcome"])
            self.assertEqual("add a note", completed["delivery"]["request"])
            self.assertEqual("chore", completed["delivery"]["kind"])
            report = evidence(root, "verified-note")
            self.assertEqual("docs: add note", report["tasks"][0]["delivery"]["outcome"])
            self.assertEqual("valid", report["tasks"][0]["local_evidence"]["status"])
            with patch("ag2c.tasks.verify_commit_receipt") as verify_receipt:
                listing = evidence(root, "verified-note", verify_local=False)
                verify_receipt.assert_not_called()
            self.assertEqual("successful", listing["tasks"][0]["management_result"])
            self.assertEqual(report["tasks"][0]["management_result"], listing["tasks"][0]["management_result"])
            self.assertEqual("recorded", listing["tasks"][0]["local_evidence"]["status"])
            self.assertFalse(worktree.exists())
            self.assertEqual("completed", list_tasks(root)[0]["worktree"]["lifecycle"])
            from ag2c.journal import list_journals

            journals = list_journals(root)
            self.assertEqual(1, len(journals))
            self.assertEqual("verified-note", journals[0]["task_id"])
            self.assertEqual("docs: add note", journals[0]["outcome"])
            self.assertEqual("chore", journals[0]["kind"])

    def test_abandon_removes_open_worktree_and_records_discard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = self.enrolled(workspace)
            task = self.start_note_task(root, workspace, "abandoned-note")
            worktree = Path(task["worktree"]["path"])
            (worktree / "NOTE.md").write_text("scratch\n", encoding="utf-8")

            abandoned = abandon_task(root, "abandoned-note", reason="no longer needed")
            self.assertEqual("abandoned", abandoned["state"])
            self.assertEqual("no longer needed", abandoned["abandon"]["reason"])
            self.assertFalse(worktree.exists())
            self.assertEqual("abandoned", list_tasks(root)[0]["worktree"]["lifecycle"])

            with self.assertRaisesRegex(AG2CError, "task is abandoned"):
                finish_task(root, "abandoned-note", message="docs: should not merge")

            report = evidence(root, "abandoned-note")
            self.assertEqual("abandoned", report["tasks"][0]["management_result"])
            self.assertTrue(report["tasks"][0]["evidence_complete"])

    def test_canonical_advance_marks_worktree_diverged_until_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = self.enrolled(workspace)
            task = self.start_note_task(root, workspace, "refresh-note")
            worktree = Path(task["worktree"]["path"])
            (worktree / "NOTE.md").write_text("from task\n", encoding="utf-8")
            source_head = head(root)

            (root / "README.md").write_text("canonical moved\n", encoding="utf-8")
            git(root, "add", "README.md")
            git(root, "-c", "core.hooksPath=", "commit", "-m", "docs: advance canonical")
            self.assertNotEqual(source_head, head(root))

            with self.assertRaisesRegex(AG2CError, "ag2c task refresh"):
                verify_task(worktree)
            self.assertEqual("diverged", list_tasks(root)[0]["worktree"]["lifecycle"])

            refreshed = refresh_task(root, "refresh-note")
            self.assertTrue(refreshed["refreshed"])
            self.assertEqual("active", refreshed["state"])
            self.assertEqual(head(root), refreshed["source"]["head"])
            self.assertEqual(source_head, refreshed["source"]["started_head"])
            self.assertEqual("canonical moved\n", (worktree / "README.md").read_text(encoding="utf-8"))
            self.assertEqual("from task\n", (worktree / "NOTE.md").read_text(encoding="utf-8"))
            self.assertEqual("in-progress", list_tasks(root)[0]["worktree"]["lifecycle"])

            self.assertTrue(verify_task(worktree)["passed"])
            completed = finish_task(root, "refresh-note", message="docs: add note after refresh")
            self.assertEqual("completed", completed["state"])
            self.assertEqual("from task\n", (root / "NOTE.md").read_text(encoding="utf-8"))
            kinds = [item["kind"] for item in completed["interventions"]]
            self.assertIn("canonical-head-diverged", kinds)
            self.assertIn("source-refreshed", kinds)

    def test_policy_change_during_task_expands_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = self.enrolled(workspace)
            task = self.start_note_task(root, workspace, "policy-shift")
            worktree = Path(task["worktree"]["path"])
            (worktree / "NOTE.md").write_text("still governed\n", encoding="utf-8")
            manifest = load_manifest(discover_manifest(root))
            policy = json.loads(manifest.policy_path.read_text(encoding="utf-8"))
            policy["cards"].append(
                {
                    "id": "floor.extra",
                    "type": "floor",
                    "title": "Extra area",
                    "summary": "Added while a task was already open.",
                    "scopes": [{"target": "app", "include": ["extra/**"], "ownership": "primary"}],
                    "checkers": [policy["checkers"][0]["id"]],
                    "references": [],
                }
            )
            manifest.policy_path.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")

            passed = verify_task(worktree)
            self.assertTrue(passed["passed"])
            kinds = [item["kind"] for item in task_record(root, "policy-shift")["interventions"]]
            self.assertIn("governance-changed", kinds)
            finish_task(root, "policy-shift", message="docs: keep note after policy change")

    def test_cli_lists_worktree_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = self.enrolled(workspace)
            self.start_note_task(root, workspace, "listed-note", goal="track the worktree")
            previous = Path.cwd()
            output = StringIO()
            try:
                os.chdir(root)
                with redirect_stdout(output):
                    self.assertEqual(0, main(["task", "list"]))
            finally:
                os.chdir(previous)
            self.assertIn("[in-progress] listed-note - track the worktree", output.getvalue())
            self.assertIn("constructing:", output.getvalue())


if __name__ == "__main__":
    unittest.main()
