from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bootstrap

from ag2c.cli import main

from support import git_project


class CLITests(unittest.TestCase):
    def test_enroll_installs_automatic_governance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "project")
            with patch("ag2c.enrollment.Path.home", return_value=workspace):
                self.assertEqual(main(["enroll", str(root), "--project-id", "starter"]), 0)
                previous = Path.cwd()
                try:
                    os.chdir(root)
                    self.assertEqual(main(["guard", "status"]), 0)
                finally:
                    os.chdir(previous)
            self.assertTrue((root / ".ag2c" / "enrollment.json").is_file())
            self.assertIn("$ag2c-governed-development", (root / "AGENTS.md").read_text(encoding="utf-8"))
            self.assertIn("/ag2c-governed-development", (root / "CLAUDE.md").read_text(encoding="utf-8"))
            self.assertTrue((workspace / ".codex" / "skills" / "ag2c-governed-development" / "SKILL.md").is_file())
            self.assertTrue((workspace / ".claude" / "skills" / "ag2c-governed-development" / "SKILL.md").is_file())
            self.assertTrue((workspace / ".agents" / "skills" / "ag2c-governed-development" / "SKILL.md").is_file())


if __name__ == "__main__":
    unittest.main()
