from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bootstrap

from ag2c.enrollment import _native_checkers
from ag2c.harnesses import install_skills, remove_skills


class HarnessAdapterTests(unittest.TestCase):
    def test_default_install_covers_codex_claude_and_generic_agents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            codex_home = home / "custom-codex"
            with patch("ag2c.harnesses.Path.home", return_value=home), patch.dict(
                os.environ, {"CODEX_HOME": str(codex_home)}
            ):
                installed = install_skills()

            self.assertEqual(["codex", "claude", "agents"], [item["harness"] for item in installed])
            expected = [
                codex_home / "skills",
                home / ".claude" / "skills",
                home / ".agents" / "skills",
            ]
            for root in expected:
                self.assertTrue((root / "ag2c-governed-development" / "SKILL.md").is_file())
                self.assertTrue((root / "ag2c-governance-update" / "SKILL.md").is_file())

    def test_harness_selection_is_narrow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            with patch("ag2c.harnesses.Path.home", return_value=home):
                installed = install_skills(harnesses=("claude",))
            self.assertEqual(["claude"], [item["harness"] for item in installed])
            self.assertTrue((home / ".claude" / "skills" / "ag2c-governed-development" / "SKILL.md").is_file())
            self.assertFalse((home / ".agents").exists())

    def test_uninstall_removes_only_unchanged_packaged_skills(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            with patch("ag2c.harnesses.Path.home", return_value=home):
                install_skills(harnesses=("codex", "claude"))
                modified = home / ".claude" / "skills" / "ag2c-governed-development" / "SKILL.md"
                modified.write_text(modified.read_text(encoding="utf-8") + "\nlocal change\n", encoding="utf-8")
                result = remove_skills(harnesses=("codex", "claude"))

            self.assertEqual("removed", result[0]["status"])
            self.assertEqual("preserved-modified", result[1]["status"])
            self.assertFalse((home / ".codex" / "skills" / "ag2c-governed-development").exists())
            self.assertTrue(modified.is_file())

    def test_node_checker_uses_the_project_package_manager(self) -> None:
        commands = {
            "pnpm-lock.yaml": ["pnpm", "test"],
            "yarn.lock": ["yarn", "test"],
            "bun.lock": ["bun", "test"],
            "package-lock.json": ["npm", "test"],
        }
        for lockfile, expected in commands.items():
            with self.subTest(lockfile=lockfile), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "package.json").write_text('{"scripts":{"test":"node test.js"}}', encoding="utf-8")
                (root / lockfile).write_text("", encoding="utf-8")
                checker = next(item for item in _native_checkers(root) if item["id"] == "check.node")
                self.assertEqual(expected, checker["command"])
