from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import bootstrap
from support import git_project

from ag2c.enrollment import enroll_project
from ag2c.gitops import git, status_entries


class EnrollmentTests(unittest.TestCase):
    def test_enroll_allows_a_dirty_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = git_project(Path(directory) / "demo")
            (root / "src" / "value.py").write_text("VALUE = 2\n", encoding="utf-8")
            (root / "notes.txt").write_text("scratch\n", encoding="utf-8")
            skills = Path(directory) / "skills"
            dirty = status_entries(root)
            self.assertIn("src/value.py", dirty)
            self.assertIn("notes.txt", dirty)

            result = enroll_project(root, skill_root=skills, harnesses=("agents",))

            self.assertEqual("demo", result["project_id"])
            self.assertFalse(result["working_tree_changed"])
            self.assertTrue((Path(result["store"]) / "manifest.json").is_file())
            self.assertTrue(status_entries(root))
            self.assertTrue(str(git(root, "config", "--get", "ag2c.manifest")).strip())
