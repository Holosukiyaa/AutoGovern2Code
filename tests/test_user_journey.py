from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from support import git_project


class UserJourneyTests(unittest.TestCase):
    def run_cli(self, cwd: Path, *args: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            [sys.executable, "-m", "ag2c", *args],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(expected, completed.returncode, completed.stderr or completed.stdout)
        return completed

    def test_setup_repair_failed_check_fix_merge_and_plain_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "project")
            skills = workspace / "skills"
            setup = self.run_cli(
                workspace,
                "setup",
                "--project",
                str(root),
                "--project-id",
                "user-journey",
                "--skill-destination",
                str(skills),
            )
            self.assertEqual("enrolled", json.loads(setup.stdout)["action"])

            coverage = json.loads(self.run_cli(root, "coverage", "--format", "json").stdout)
            self.assertEqual("baseline", coverage["level"])
            self.assertGreaterEqual(coverage["area_count"], 2)
            self.assertEqual("conservative", coverage["strategy"])

            (root / ".ag2c" / "state" / "hooks" / "pre-commit").unlink()
            self.run_cli(
                root,
                "doctor",
                "--repair",
                "--skill-destination",
                str(skills),
            )

            started = json.loads(
                self.run_cli(
                    root,
                    "task",
                    "start",
                    "--goal",
                    "change the managed value",
                    "--path",
                    "app:src/value.py",
                    "--task-id",
                    "user-value-change",
                    "--worktree-root",
                    str(workspace / "worktrees"),
                ).stdout
            )
            worktree = Path(started["worktree"]["path"])
            (worktree / "src" / "value.py").write_text("VALUE = 2\n", encoding="utf-8")
            failed = json.loads(self.run_cli(worktree, "task", "verify", expected=1).stdout)
            self.assertFalse(failed["passed"])

            test_file = worktree / "tests" / "test_value.py"
            test_file.write_text(
                test_file.read_text(encoding="utf-8").replace("VALUE, 1", "VALUE, 2"),
                encoding="utf-8",
            )
            passed = json.loads(self.run_cli(worktree, "task", "verify").stdout)
            self.assertTrue(passed["passed"])
            completed = json.loads(
                self.run_cli(
                    root,
                    "task",
                    "finish",
                    "--task",
                    "user-value-change",
                    "--message",
                    "feat: change managed value",
                ).stdout
            )
            self.assertEqual("completed", completed["state"])

            plain = self.run_cli(root, "evidence", "--task", "user-value-change").stdout
            self.assertIn("Management: successful", plain)
            self.assertIn("Files changed: 2", plain)
            self.assertIn("AI correction: proven after 1 failed attempt(s)", plain)
            self.assertIn("Evidence: complete", plain)
            report = json.loads(
                self.run_cli(root, "evidence", "--task", "user-value-change", "--format", "json").stdout
            )
            self.assertTrue(report["tasks"][0]["correction_proven"])
            self.assertEqual(2, report["tasks"][0]["checks_run"])


if __name__ == "__main__":
    unittest.main()
