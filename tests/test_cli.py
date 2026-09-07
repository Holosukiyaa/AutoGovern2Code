from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import bootstrap

from ag2c import __version__, tasks
from ag2c.cli import main
from ag2c.errors import AG2CError


class CLITests(unittest.TestCase):
    def test_browser_viewer_command_is_removed(self) -> None:
        output = io.StringIO()
        with patch("ag2c_gui.desktop.serve_desktop") as serve, redirect_stdout(output):
            with self.assertRaises(SystemExit):
                main(["viewer", "--open"])
        serve.assert_not_called()

    def test_project_uninstall_removes_governance_data(self) -> None:
        output = io.StringIO()
        with patch("ag2c.management.stop_managing", return_value={"uninstalled": True, "data_removed": True}) as stop, redirect_stdout(output):
            self.assertEqual(0, main(["project", "uninstall", "C:/tmp/project"]))
        stop.assert_called_once()
        self.assertTrue(stop.call_args.kwargs["remove_data"])

    def test_skill_prompt_prints_plain_entry_text(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(0, main(["skill", "prompt", "--project", "."]))
        text = output.getvalue()
        self.assertIn("ag2c skill install", text)
        self.assertIn("ag2c skill version", text)
        self.assertIn("ag2c guard status", text)
        self.assertIn("docs/skills/ag2c-governed-development", text)
        self.assertIn("ag2c-directory-census", text)
        self.assertIn("ag2c-knowledge-authoring", text)
        self.assertIn(f"version {__version__}", text)
        self.assertIn("replace the installed copy if missing or different", text)

    def test_skill_version_prints_packaged_identity(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(0, main(["skill", "version"]))
        payload = json.loads(output.getvalue())
        self.assertEqual(__version__, payload["package"])
        self.assertEqual(
            ["ag2c-governed-development", "ag2c-governance-update", "ag2c-directory-census", "ag2c-knowledge-authoring"],
            [item["name"] for item in payload["skills"]],
        )
        for item in payload["skills"]:
            self.assertEqual(__version__, item["version"])
            self.assertTrue(item["digest"])


class WorktreeLocationTests(unittest.TestCase):
    def test_outside_worktree_needs_no_ignore_rule(self) -> None:
        with patch("ag2c.tasks.git") as runner:
            tasks._ensure_worktree_location(Path("C:/repo"), Path("D:/ag2c-worktrees/task-1"))
        runner.assert_not_called()

    def test_in_checkout_worktree_allowed_when_git_ignores_it(self) -> None:
        worktree = Path("C:/repo/data/projects/key/worktrees/task-1")
        with patch("ag2c.tasks.git", return_value="data/projects/key/worktrees/task-1\n") as runner:
            tasks._ensure_worktree_location(Path("C:/repo"), worktree)
        runner.assert_called_once()
        self.assertEqual("check-ignore", runner.call_args.args[1])

    def test_in_checkout_worktree_refused_when_not_ignored(self) -> None:
        with patch("ag2c.tasks.git", return_value=""):
            with self.assertRaises(AG2CError):
                tasks._ensure_worktree_location(Path("C:/repo"), Path("C:/repo/src/worktrees/task-1"))
