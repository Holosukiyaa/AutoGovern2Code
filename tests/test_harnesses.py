from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bootstrap

from ag2c.enrollment import _native_checkers
from ag2c.harnesses import harness_status, install_skills, remove_skills, skill_entry_prompt


class HarnessAdapterTests(unittest.TestCase):
    def test_skill_entry_prompt_tells_the_agent_to_install_into_its_own_home(self) -> None:
        prompt = skill_entry_prompt(project=Path(tempfile.gettempdir()))
        self.assertIn("docs/skills/ag2c-governed-development", prompt)
        self.assertIn("ag2c skill install", prompt)
        self.assertIn("ag2c guard status", prompt)
        self.assertIn("~/.codex/skills", prompt)
        self.assertNotIn(str(Path(tempfile.gettempdir()) / "docs" / "skills"), prompt)
        repo = Path(__file__).resolve().parents[1]
        local = skill_entry_prompt(project=repo)
        self.assertIn("Local skill copy in this repo:", local)
        self.assertIn("docs", local.casefold())

    def test_default_install_covers_codex_claude_cursor_and_generic_agents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            codex_home = home / "custom-codex"
            with patch("ag2c.harnesses.Path.home", return_value=home), patch.dict(
                os.environ, {"CODEX_HOME": str(codex_home)}
            ):
                installed = install_skills()

            self.assertEqual(["codex", "claude", "cursor", "agents"], [item["harness"] for item in installed])
            expected = [
                codex_home / "skills",
                home / ".claude" / "skills",
                home / ".cursor" / "skills",
                home / ".agents" / "skills",
            ]
            for root in expected:
                self.assertTrue((root / "ag2c-governed-development" / "SKILL.md").is_file())
                self.assertTrue((root / "ag2c-governance-update" / "SKILL.md").is_file())

    def test_cursor_is_detected_from_user_config_dir(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".cursor").mkdir()
            with patch("ag2c.harnesses.Path.home", return_value=home), patch(
                "ag2c.harnesses.shutil.which", return_value=None
            ):
                status = {item["harness"]: item for item in harness_status()}
            self.assertTrue(status["cursor"]["detected"])
            self.assertEqual("skill-missing", status["cursor"]["state"])
            self.assertEqual(str((home / ".cursor" / "skills" / "ag2c-governed-development").resolve()), status["cursor"]["skill_path"])
            self.assertFalse(str(status["cursor"]["skill_path"]).replace("\\", "/").endswith("skills-cursor/ag2c-governed-development"))

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
