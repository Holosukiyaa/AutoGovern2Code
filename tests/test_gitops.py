from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ag2c.gitops import change_digest, commit_change_digest, git, head

from support import git_project


class GitDigestTests(unittest.TestCase):
    def test_filemode_false_preserves_a_tracked_executable_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = git_project(Path(directory) / "project")
            script = root / "tool.sh"
            script.write_text("#!/bin/sh\necho first\n", encoding="utf-8")
            git(root, "add", "tool.sh")
            git(root, "update-index", "--chmod=+x", "tool.sh")
            git(root, "commit", "-m", "add executable")
            base = head(root)
            git(root, "config", "core.fileMode", "false")
            script.write_text("#!/bin/sh\necho second\n", encoding="utf-8")

            worktree_digest = change_digest(root, base)
            git(root, "add", "tool.sh")
            git(root, "commit", "-m", "change executable")

            self.assertEqual(worktree_digest, commit_change_digest(root, base, head(root)))
