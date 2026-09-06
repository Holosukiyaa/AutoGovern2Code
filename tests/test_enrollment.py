from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bootstrap
from support import git_project

from ag2c.config import discover_manifest, load_manifest, load_policy
from ag2c.enrollment import activation_status, enroll_project
from ag2c.errors import AG2CError
from ag2c.gitops import git, status_entries
from ag2c.household_commands import register_household, tighten_household
from ag2c.households import census_report


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

    def test_activate_wraps_every_previous_git_hook(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = git_project(base / "demo")
            husky = root / ".husky"
            husky.mkdir()
            (husky / "pre-commit").write_text("#!/bin/sh\necho old-pre-commit\n", encoding="utf-8")
            (husky / "pre-push").write_text("#!/bin/sh\necho old-pre-push\n", encoding="utf-8")
            (husky / "commit-msg").write_text("#!/bin/sh\necho old-commit-msg\n", encoding="utf-8")
            (husky / "not-a-hook").write_text("ignore\n", encoding="utf-8")
            git(root, "config", "core.hooksPath", ".husky")
            data = base / "ag2c-data"
            skills = base / "skills"
            with patch.dict(os.environ, {"AG2C_DATA_ROOT": str(data)}, clear=False):
                result = enroll_project(root, skill_root=skills, harnesses=("agents",))
            hooks = Path(result["store"]) / "state" / "hooks"
            pre = (hooks / "pre-commit").read_text(encoding="utf-8")
            push = (hooks / "pre-push").read_text(encoding="utf-8")
            message = (hooks / "commit-msg").read_text(encoding="utf-8")
            self.assertIn("guard pre-commit", pre)
            self.assertIn((husky / "pre-commit").resolve().as_posix(), pre.replace("\\", "/"))
            self.assertIn((husky / "pre-push").resolve().as_posix(), push.replace("\\", "/"))
            self.assertNotIn("guard pre-commit", push)
            self.assertIn((husky / "commit-msg").resolve().as_posix(), message.replace("\\", "/"))
            self.assertFalse((hooks / "not-a-hook").exists())
            self.assertEqual(str(hooks.resolve()), str(git(root, "config", "--get", "core.hooksPath")).strip())
            self.assertEqual(".husky", json.loads((Path(result["store"]) / "state" / "activation.json").read_text(encoding="utf-8"))["previous_hooks_path"])

    def test_activate_forwards_default_git_hooks_and_ignores_samples(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = git_project(base / "demo")
            native = root / ".git" / "hooks"
            native.mkdir(parents=True, exist_ok=True)
            (native / "pre-push").write_text("#!/bin/sh\necho native-pre-push\n", encoding="utf-8")
            (native / "pre-commit.sample").write_text("#!/bin/sh\necho sample\n", encoding="utf-8")
            data = base / "ag2c-data"
            with patch.dict(os.environ, {"AG2C_DATA_ROOT": str(data)}, clear=False):
                result = enroll_project(root, skill_root=base / "skills", harnesses=("agents",))
            hooks = Path(result["store"]) / "state" / "hooks"
            push = (hooks / "pre-push").read_text(encoding="utf-8")
            self.assertIn((native / "pre-push").resolve().as_posix(), push.replace("\\", "/"))
            self.assertNotIn("native-pre-push", push)
            self.assertFalse((hooks / "pre-commit.sample").exists())
            self.assertIn("guard pre-commit", (hooks / "pre-commit").read_text(encoding="utf-8"))

    def test_stale_skill_home_does_not_unmanage_when_git_guard_is_on(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = git_project(base / "demo")
            skills = base / "skills"
            data = base / "ag2c-data"
            with patch.dict(os.environ, {"AG2C_DATA_ROOT": str(data)}, clear=False):
                enroll_project(root, skill_root=skills, harnesses=("agents",))
                skill_md = skills / "ag2c-governed-development" / "SKILL.md"
                skill_md.write_text("---\nname: ag2c-governed-development\nversion: 0.0.1\n---\nstale\n", encoding="utf-8")
                status = activation_status(root)
            self.assertTrue(status["managed"])
            self.assertFalse(any("Skill" in item for item in status["issues"]))

    def test_naming_src_without_child_households_is_refused_not_stored_as_opaque(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = git_project(base / "demo")
            (root / "src" / "frontend").mkdir()
            (root / "src" / "frontend" / "app.ts").write_text("export {}\n", encoding="utf-8")
            (root / "src" / "backend").mkdir()
            (root / "src" / "backend" / "api.py").write_text("VALUE = 1\n", encoding="utf-8")
            data = base / "ag2c-data"
            with patch.dict(os.environ, {"AG2C_DATA_ROOT": str(data)}, clear=False):
                enroll_project(root, skill_root=base / "skills", harnesses=("agents",))
                with self.assertRaises(AG2CError) as raised:
                    register_household(
                        root,
                        card_id="knowledge.src",
                        title="src",
                        summary="the whole tree",
                        includes=["src/**"],
                        excludes=[],
                        floors=["floor.src"],
                        capability="src",
                        implementation="src.main",
                        status="current",
                        meaning="named",
                        actor="codex",
                        reason="claim every file under src",
                    )
                self.assertIn("cannot-name-undecomposed-household", str(raised.exception))
                with self.assertRaises(AG2CError) as tightened:
                    tighten_household(
                        root,
                        card_id="knowledge.src",
                        meaning="named",
                        actor="codex",
                        reason="name the enrollment placeholder",
                    )
                self.assertIn("tighten-blocked", str(tightened.exception))
                manifest = load_manifest(discover_manifest(root), project_root=root)
                src = next(item for item in census_report(manifest, load_policy(manifest))["households"] if item["id"] == "knowledge.src")
                self.assertEqual("exploring", src["identity"])
                frontend = register_household(
                    root,
                    card_id="knowledge.frontend",
                    title="frontend",
                    summary="shipped UI",
                    includes=["src/frontend/**"],
                    excludes=[],
                    floors=["floor.src"],
                    capability="frontend",
                    implementation="frontend.main",
                    status="current",
                    meaning="named",
                    actor="codex",
                    reason="traced the UI subtree",
                )
            self.assertEqual("named", frontend["jurisdiction"]["meaning"])

    def test_parent_glob_cannot_recapture_child_household(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = git_project(base / "demo")
            (root / "src" / "frontend").mkdir()
            (root / "src" / "frontend" / "app.ts").write_text("export {}\n", encoding="utf-8")
            data = base / "ag2c-data"
            with patch.dict(os.environ, {"AG2C_DATA_ROOT": str(data)}, clear=False):
                enroll_project(root, skill_root=base / "skills", harnesses=("agents",))
                register_household(
                    root,
                    card_id="knowledge.frontend",
                    title="frontend",
                    summary="shipped UI",
                    includes=["src/frontend/**"],
                    excludes=[],
                    floors=["floor.src"],
                    capability="frontend",
                    implementation="frontend.main",
                    status="current",
                    meaning="named",
                    actor="codex",
                    reason="traced the UI subtree",
                )
                with self.assertRaises(AG2CError) as raised:
                    register_household(
                        root,
                        card_id="knowledge.src",
                        title="src",
                        summary="the whole tree",
                        includes=["src/**"],
                        excludes=[],
                        floors=["floor.src"],
                        capability="src",
                        implementation="src.main",
                        status="current",
                        meaning="named",
                        actor="codex",
                        reason="reclaim src after carving frontend",
                    )
                self.assertIn("cannot-overlap-household", str(raised.exception))
                self.assertNotIn("cannot-name-undecomposed-household", str(raised.exception))
                manifest = load_manifest(discover_manifest(root), project_root=root)
                report = census_report(manifest, load_policy(manifest))
            src = next(item for item in report["households"] if item["id"] == "knowledge.src")
            frontend = next(item for item in report["households"] if item["id"] == "knowledge.frontend")
            frontend_dir = next(item for item in report["directories"] if item["path"] == "src/frontend")
            src_excludes = [
                pattern
                for scope in src["scopes"]
                for pattern in (scope.get("exclude") or scope.get("excludes") or [])
            ]
            self.assertEqual("exploring", src["identity"])
            self.assertEqual("named", frontend["identity"])
            self.assertEqual(["knowledge.frontend"], frontend_dir["owners"])
            self.assertIn("src/frontend/**", src_excludes)
            self.assertEqual(0, report["counts"]["ambiguous"])
