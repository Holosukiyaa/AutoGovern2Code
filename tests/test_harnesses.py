from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bootstrap

from ag2c import __version__
from ag2c.enrollment import _native_checkers
from ag2c.harnesses import (
    PACKAGED_SKILLS,
    harness_status,
    install_skills,
    packaged_skill_identity,
    packaged_skills_report,
    remove_skills,
    skill_entry_prompt,
    skill_frontmatter_version,
    skill_source,
)


class HarnessAdapterTests(unittest.TestCase):
    def test_skill_entry_prompt_tells_the_agent_to_install_into_its_own_home(self) -> None:
        prompt = skill_entry_prompt(project=Path(tempfile.gettempdir()))
        self.assertNotIn("docs/skills", prompt)
        self.assertIn("ag2c skill install", prompt)
        self.assertIn("ag2c skill version", prompt)
        self.assertIn("ag2c guard status", prompt)
        self.assertIn("~/.codex/skills", prompt)
        self.assertIn(f"version {__version__}", prompt)
        self.assertIn("replace the installed copy if missing or different", prompt)
        self.assertIn("this AutoGovern2Code's packaged copy", prompt)
        self.assertIn("do not keep a higher version from elsewhere", prompt)
        self.assertNotIn(str(Path(tempfile.gettempdir()) / "docs" / "skills"), prompt)
        for name in PACKAGED_SKILLS:
            identity = packaged_skill_identity(name)
            self.assertIn(f"{name} version {identity['version']} digest {identity['digest'][:12]}", prompt)

    def test_packaged_skills_declare_this_ag2c_version(self) -> None:
        report = packaged_skills_report()
        self.assertEqual(__version__, report["package"])
        self.assertEqual(list(PACKAGED_SKILLS), [item["name"] for item in report["skills"]])
        for name in PACKAGED_SKILLS:
            packaged = skill_source(name) / "SKILL.md"
            self.assertEqual(__version__, skill_frontmatter_version(packaged))

    def test_install_replaces_a_different_skill_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / "skills"
            stale = dest / "ag2c-governed-development"
            stale.mkdir(parents=True)
            (stale / "SKILL.md").write_text(
                "---\nname: ag2c-governed-development\nversion: 0.0.1\n---\nstale copy\n",
                encoding="utf-8",
            )
            installed = install_skills(dest)
            text = (dest / "ag2c-governed-development" / "SKILL.md").read_text(encoding="utf-8")
            self.assertEqual("custom", installed[0]["harness"])
            self.assertEqual(__version__, installed[0]["version"])
            self.assertEqual(__version__, skill_frontmatter_version(dest / "ag2c-governed-development" / "SKILL.md"))
            self.assertNotIn("stale copy", text)

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
                self.assertTrue((root / "ag2c-directory-census" / "SKILL.md").is_file())
                self.assertTrue((root / "ag2c-knowledge-authoring" / "SKILL.md").is_file())
                self.assertTrue((root / "ag2c-full-liquidation" / "SKILL.md").is_file())

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
