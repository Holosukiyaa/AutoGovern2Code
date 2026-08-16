from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from ag2c.enrollment import activate_project, activation_status, enroll_project, guard_pre_commit
from ag2c.errors import AG2CError
from ag2c.gitops import git, head
from ag2c.tasks import evidence, finish_task, start_task, verify_task

from support import git_project


class AutomaticGovernanceTests(unittest.TestCase):
    def enrolled(self, workspace: Path) -> Path:
        root = git_project(workspace / "project")
        enroll_project(root, project_id="managed-project", skill_root=workspace / "skills")
        return root

    def test_enrollment_activates_skill_agent_gate_and_hook(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = self.enrolled(workspace)
            status = activation_status(root)
            self.assertTrue(status["managed"], status)
            self.assertTrue((workspace / "skills" / "ag2c-governed-development" / "SKILL.md").is_file())
            self.assertIn("Do not edit this canonical checkout", (root / "AGENTS.md").read_text(encoding="utf-8"))
            enrollment = json.loads((root / ".ag2c" / "enrollment.json").read_text(encoding="utf-8"))
            self.assertEqual("ag2c.enrollment.v1", enrollment["schema"])
            self.assertEqual("chore: enroll project in AG2C", str(git(root, "log", "-1", "--pretty=%s")).strip())

    def test_canonical_commit_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.enrolled(Path(directory))
            (root / "src" / "value.py").write_text("VALUE = 2\n", encoding="utf-8")
            git(root, "add", "src/value.py")
            with self.assertRaisesRegex(AG2CError, "blocks commits in the canonical worktree"):
                guard_pre_commit(root)
            completed = subprocess.run(
                ["git", "-C", str(root), "commit", "-m", "bypass"],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertNotEqual(0, completed.returncode)
            self.assertIn("canonical worktree", completed.stderr)

    def test_existing_pre_commit_hook_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "project")
            common = Path(str(git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")).strip())
            existing_hook = common / "hooks" / "pre-commit"
            proof = (workspace / "existing-hook-ran.txt").resolve().as_posix()
            existing_hook.write_text(f"#!/bin/sh\nprintf delegated > '{proof}'\n", encoding="utf-8", newline="\n")
            existing_hook.chmod(0o755)
            enroll_project(root, project_id="managed-project", skill_root=workspace / "skills")
            (workspace / "existing-hook-ran.txt").unlink()
            task = start_task(
                root,
                goal="exercise the existing hook",
                path_specs=["app:tests/test_value.py"],
                contract_specs=[],
                task_id="existing-hook",
                worktree_root=workspace / "worktrees",
            )
            worktree = Path(task["worktree"]["path"])
            test_file = worktree / "tests" / "test_value.py"
            test_file.write_text(test_file.read_text(encoding="utf-8") + "\n# hook coverage\n", encoding="utf-8")
            self.assertTrue(verify_task(worktree)["passed"])

            finish_task(root, "existing-hook", message="test: exercise existing hook")

            self.assertEqual("delegated", (workspace / "existing-hook-ran.txt").read_text(encoding="utf-8"))

    def test_commit_hook_cannot_replace_verified_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = self.enrolled(workspace)
            previous_hooks = workspace / "previous-hooks"
            previous_hooks.mkdir()
            hook = previous_hooks / "pre-commit"
            hook.write_text(
                "#!/bin/sh\nprintf '\\n# changed by hook\\n' >> tests/test_value.py\ngit add tests/test_value.py\n",
                encoding="utf-8",
                newline="\n",
            )
            hook.chmod(0o755)
            git(root, "config", "core.hooksPath", str(previous_hooks))
            activate_project(root, skill_root=workspace / "skills")
            source_head = head(root)
            task = start_task(
                root,
                goal="prove exact commit bytes",
                path_specs=["app:tests/test_value.py"],
                contract_specs=[],
                task_id="hook-mutation",
                worktree_root=workspace / "worktrees",
            )
            worktree = Path(task["worktree"]["path"])
            test_file = worktree / "tests" / "test_value.py"
            test_file.write_text(test_file.read_text(encoding="utf-8") + "\n# intended change\n", encoding="utf-8")
            self.assertTrue(verify_task(worktree)["passed"])

            with self.assertRaisesRegex(AG2CError, "commit hooks changed the verified bytes"):
                finish_task(root, "hook-mutation", message="test: prove exact bytes")

            self.assertEqual(source_head, head(root))
            record = evidence(root, "hook-mutation")["tasks"][0]
            self.assertEqual("commit-hook-mutated-change", record["interventions"][-1]["kind"])

    def test_task_record_cannot_forge_passing_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = self.enrolled(workspace)
            task = start_task(
                root,
                goal="prove verification integrity",
                path_specs=["app:tests/test_value.py"],
                contract_specs=[],
                task_id="tampered-verification",
                worktree_root=workspace / "worktrees",
            )
            worktree = Path(task["worktree"]["path"])
            test_file = worktree / "tests" / "test_value.py"
            test_file.write_text(test_file.read_text(encoding="utf-8") + "\n# evidence coverage\n", encoding="utf-8")
            self.assertTrue(verify_task(worktree)["passed"])
            record_path = root / ".ag2c" / "state" / "tasks" / "tampered-verification.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["verifications"][-1]["change_digest"] = "0" * 64
            record_path.write_text(json.dumps(record), encoding="utf-8")

            with self.assertRaisesRegex(AG2CError, "evidence is missing or inconsistent"):
                finish_task(root, "tampered-verification", message="test: reject forged evidence")
            self.assertFalse(evidence(root, "tampered-verification")["tasks"][0]["evidence_complete"])

    def test_deleting_agents_file_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = self.enrolled(workspace)
            task = start_task(
                root,
                goal="attempt to delete the instructions",
                path_specs=["app:AGENTS.md"],
                contract_specs=[],
                task_id="delete-agents",
                worktree_root=workspace / "worktrees",
            )
            worktree = Path(task["worktree"]["path"])
            (worktree / "AGENTS.md").unlink()
            with self.assertRaisesRegex(AG2CError, "governance controls"):
                verify_task(worktree)

    def test_changed_skill_invalidates_activation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = self.enrolled(workspace)
            skill = workspace / "skills" / "ag2c-governed-development" / "SKILL.md"
            skill.write_text(skill.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
            status = activation_status(root)
            self.assertFalse(status["managed"])
            self.assertIn("installed AG2C Skill changed after activation", status["issues"])

            stale = skill.parent / "stale.txt"
            stale.write_text("old Skill residue\n", encoding="utf-8")
            activate_project(root, skill_root=workspace / "skills")
            self.assertFalse(stale.exists())
            self.assertTrue(activation_status(root)["managed"])

    def test_enrollment_preserves_existing_crlf_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "project")
            (root / "AGENTS.md").write_bytes(b"# Existing rules\r\n\r\nKeep this text.\r\n")
            (root / ".gitignore").write_bytes(b"__pycache__/\r\n*.pyc\r\nlocal.env\r\n")
            git(root, "add", "AGENTS.md", ".gitignore")
            git(root, "commit", "-m", "docs: add project instructions")

            enroll_project(root, project_id="managed-project", skill_root=workspace / "skills")

            for path in (root / "AGENTS.md", root / ".gitignore"):
                content = path.read_bytes()
                self.assertNotIn(b"\n", content.replace(b"\r\n", b""))
            self.assertIn(b"Keep this text.\r\n", (root / "AGENTS.md").read_bytes())
            self.assertIn(b"local.env\r\n", (root / ".gitignore").read_bytes())

    def test_branch_name_alone_cannot_bypass_task_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = self.enrolled(workspace)
            fake = workspace / "fake-worktree"
            git(root, "worktree", "add", "-b", "ag2c/fake", str(fake), head(root))
            (fake / "src" / "value.py").write_text("VALUE = 2\n", encoding="utf-8")
            with self.assertRaisesRegex(AG2CError, "valid active task record"):
                guard_pre_commit(fake)

    def test_new_top_level_file_is_governed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = self.enrolled(workspace)
            task = start_task(
                root,
                goal="add a top-level note",
                path_specs=["app:NOTE.md"],
                contract_specs=[],
                task_id="top-level-note",
                worktree_root=workspace / "worktrees",
            )
            worktree = Path(task["worktree"]["path"])
            (worktree / "NOTE.md").write_text("managed\n", encoding="utf-8")
            self.assertTrue(verify_task(worktree)["passed"])
            completed = finish_task(root, "top-level-note", message="docs: add managed note")
            self.assertEqual("managed\n", (root / "NOTE.md").read_text(encoding="utf-8"))
            self.assertEqual("completed", completed["state"])

    def test_failed_verification_then_fix_proves_ai_correction_and_merges(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = self.enrolled(workspace)
            source_head = head(root)
            task = start_task(
                root,
                goal="change the managed value",
                path_specs=["app:src/value.py"],
                contract_specs=[],
                task_id="value-change",
                worktree_root=workspace / "worktrees",
            )
            worktree = Path(task["worktree"]["path"])
            (worktree / "src" / "value.py").write_text("VALUE = 2\n", encoding="utf-8")
            first = verify_task(worktree)
            self.assertFalse(first["passed"])

            test_file = worktree / "tests" / "test_value.py"
            test_file.write_text(test_file.read_text(encoding="utf-8").replace("VALUE, 1", "VALUE, 2"), encoding="utf-8")
            second = verify_task(worktree)
            self.assertTrue(second["passed"], second)

            completed = finish_task(root, "value-change", message="feat: change managed value")
            self.assertEqual("completed", completed["state"])
            self.assertNotEqual(source_head, head(root))
            self.assertEqual("VALUE = 2\n", (root / "src" / "value.py").read_text(encoding="utf-8"))
            kinds = [item["kind"] for item in completed["interventions"]]
            self.assertIn("verification-failed", kinds)
            self.assertIn("scope-expanded", kinds)
            self.assertIn("ai-correction-proven", kinds)
            report = evidence(root, "value-change")
            self.assertTrue(report["managed"])
            self.assertTrue(report["ledger_valid"])
            self.assertTrue(report["tasks"][0]["verified"])
            self.assertTrue(report["tasks"][0]["evidence_complete"])
            self.assertEqual("successful", report["tasks"][0]["management_result"])
            self.assertEqual(completed["result"]["commit"], report["tasks"][0]["result"]["commit"])

            record_path = root / ".ag2c" / "state" / "tasks" / "value-change.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["start_ledger_event_digest"] = "0" * 64
            record_path.write_text(json.dumps(record), encoding="utf-8")
            tampered = evidence(root, "value-change")
            self.assertTrue(tampered["ledger_valid"])
            self.assertFalse(tampered["tasks"][0]["evidence_complete"])
            self.assertEqual("incomplete", tampered["tasks"][0]["management_result"])

    def test_change_after_passing_verification_blocks_finish(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = self.enrolled(workspace)
            task = start_task(
                root,
                goal="update the test while preserving behavior",
                path_specs=["app:tests/test_value.py"],
                contract_specs=[],
                task_id="stale-proof",
                worktree_root=workspace / "worktrees",
            )
            worktree = Path(task["worktree"]["path"])
            test_file = worktree / "tests" / "test_value.py"
            test_file.write_text(test_file.read_text(encoding="utf-8") + "\n# verified comment\n", encoding="utf-8")
            self.assertTrue(verify_task(worktree)["passed"])
            test_file.write_text(test_file.read_text(encoding="utf-8") + "# changed later\n", encoding="utf-8")
            with self.assertRaisesRegex(AG2CError, "changed after verification"):
                finish_task(root, "stale-proof", message="test: update value coverage")

    def test_formal_write_blocks_task_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = self.enrolled(workspace)
            task = start_task(
                root,
                goal="change value",
                path_specs=["app:src/value.py"],
                contract_specs=[],
                task_id="blocked-change",
                worktree_root=workspace / "worktrees",
            )
            worktree = Path(task["worktree"]["path"])
            (worktree / "src" / "value.py").write_text("VALUE = 2\n", encoding="utf-8")
            (root / "src" / "value.py").write_text("VALUE = 3\n", encoding="utf-8")
            with self.assertRaisesRegex(AG2CError, "canonical worktree changed"):
                verify_task(worktree)
            record = evidence(root, "blocked-change")["tasks"][0]
            self.assertEqual("canonical-write-blocked", record["interventions"][-1]["kind"])


if __name__ == "__main__":
    unittest.main()
