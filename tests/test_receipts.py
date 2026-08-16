from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bootstrap

from ag2c.enrollment import enroll_project
from ag2c.errors import AG2CError
from ag2c.gitops import change_digest, changed_paths, git, head
from ag2c.receipts import verify_commit_receipt
from ag2c.tasks import finish_task, start_task, verify_task
from ag2c.util import digest_json

from support import git_project, write_project


class ExternalEvidenceTests(unittest.TestCase):
    def test_externalized_v05_receipt_remains_locally_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "project")
            write_project(root)
            git(root, "add", ".ag2c", "src")
            git(root, "commit", "-m", "chore: add legacy enrollment")
            source = head(root)

            store = workspace / "external"
            store.mkdir()
            legacy_manifest = json.loads((root / ".ag2c" / "manifest.json").read_text(encoding="utf-8"))
            external_manifest = dict(legacy_manifest)
            external_manifest["project"] = {"id": "test-project", "root": str(root)}
            external_manifest["policy"] = "policy.json"
            external_manifest["state_dir"] = "state"
            external_manifest["ledger"] = "ledger.jsonl"
            (store / "manifest.json").write_text(json.dumps(external_manifest), encoding="utf-8")
            (store / "policy.json").write_bytes((root / ".ag2c" / "policy.json").read_bytes())
            git(root, "config", "--local", "ag2c.manifest", str(store / "manifest.json"))

            (root / "NOTE.md").write_text("legacy proof\n", encoding="utf-8")
            task_id = "legacy-note"
            receipt = {
                "schema": "ag2c.receipt.v1",
                "project": "test-project",
                "task_id": task_id,
                "goal": "add a legacy note",
                "source_commit": source,
                "source_branch": "main",
                "entry": {"paths": ["app:NOTE.md"], "contracts": [], "all": False},
                "changed_paths": changed_paths(root, source, exclude_prefixes=(".ag2c/receipts",)),
                "change_digest": change_digest(root, source, exclude_prefixes=(".ag2c/receipts",)),
                "route": {"state": "precise", "fallback_reasons": [], "fallback_targets": [], "cards": ["floor.project"], "slice_digest": "legacy"},
                "checks": [{"id": "check.legacy", "stage": "floor", "status": "passed", "exit_code": 0}],
                "acceptance": {"static": "not-applicable", "floor": "passed", "boundary": "not-applicable", "scenario": "not-applicable", "complete": "not-run"},
                "verification_attempts": 1,
                "failed_attempts": 0,
                "correction_proven": False,
                "blocked_actions": [],
                "manifest_blob": str(git(root, "rev-parse", "HEAD:.ag2c/manifest.json")).strip(),
                "policy_blob": str(git(root, "rev-parse", "HEAD:.ag2c/policy.json")).strip(),
                "local_evidence": {},
                "verified_at": "2026-08-16T00:00:00+00:00",
            }
            receipt["receipt_digest"] = digest_json(receipt)
            relative = root / ".ag2c" / "receipts" / f"{task_id}.json"
            relative.parent.mkdir()
            encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
            relative.write_text(encoded, encoding="utf-8")
            (store / "receipts").mkdir()
            (store / "receipts" / f"{task_id}.json").write_text(encoded, encoding="utf-8")
            git(root, "add", "NOTE.md", str(relative.relative_to(root)))
            git(root, "commit", "-m", f"docs: add legacy note\n\nAG2C-Receipt: .ag2c/receipts/{task_id}.json")

            report = verify_commit_receipt(root)
            self.assertEqual("valid", report["local_evidence"])
            self.assertEqual(receipt["receipt_digest"], report["receipt_digest"])

    def test_external_evidence_survives_prior_task_commit_and_reruns_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "项目 with spaces")
            enroll_project(root, project_id="local-evidence-project", skill_root=workspace / "skills")
            task = start_task(
                root,
                goal="add a locally evidenced note",
                path_specs=["app:NOTE.md"],
                contract_specs=[],
                task_id="local-note",
                worktree_root=workspace / "worktrees",
            )
            worktree = Path(task["worktree"]["path"])
            (worktree / "NOTE.md").write_text("local proof\n", encoding="utf-8")
            git(worktree, "add", "NOTE.md")
            git(worktree, "commit", "-m", "docs: checkpoint note")
            self.assertTrue(verify_task(worktree)["passed"])

            completed = finish_task(root, "local-note", message="docs: add local note")
            receipt_path = Path(completed["result"]["receipt_path"])
            self.assertTrue(receipt_path.is_file())
            self.assertFalse((root / ".ag2c").exists())
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual("ag2c.receipt.v2", receipt["schema"])
            self.assertEqual(["NOTE.md"], receipt["changed_paths"])
            report = verify_commit_receipt(root, completed["result"]["commit"], rerun=True)
            self.assertEqual("valid", report["local_evidence"])
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
            receipt_path = Path(completed["result"]["receipt_path"])
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["goal"] = "forged goal"
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(AG2CError, "evidence digest mismatch"):
                verify_commit_receipt(root, completed["result"]["commit"])

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
