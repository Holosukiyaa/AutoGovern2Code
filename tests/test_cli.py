from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deg.cli import main

from support import git_project


class CLITests(unittest.TestCase):
    def test_enroll_installs_automatic_governance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "project")
            codex_home = workspace / "codex-home"
            with patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}):
                self.assertEqual(main(["enroll", str(root), "--project-id", "starter"]), 0)
                previous = Path.cwd()
                try:
                    os.chdir(root)
                    self.assertEqual(main(["guard", "status"]), 0)
                finally:
                    os.chdir(previous)
            self.assertTrue((root / ".deg" / "enrollment.json").is_file())
            self.assertIn("$deg-governed-development", (root / "AGENTS.md").read_text(encoding="utf-8"))
            self.assertTrue((codex_home / "skills" / "deg-governed-development" / "SKILL.md").is_file())


if __name__ == "__main__":
    unittest.main()
