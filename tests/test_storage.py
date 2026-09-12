from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bootstrap  # noqa: F401
from support import git_project

from ag2c import storage
from ag2c.enrollment import activation_status, enroll_project
from ag2c.gitops import git


def _portable_env(home: Path, profile: Path) -> dict[str, str]:
    return {
        "AG2C_PORTABLE": str(home),
        "HOME": str(profile),
        "USERPROFILE": str(profile),
        "CODEX_HOME": str(profile / ".codex"),
        "AG2C_DATA_ROOT": "",
    }


class PortableMoveTests(unittest.TestCase):
    def test_moving_portable_home_rebinds_guard_and_restores_management(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = git_project(base / "demo")
            profile = base / "profile"
            profile.mkdir()
            home_a = base / "portable-a"
            home_a.mkdir()
            skills = base / "skills"
            with patch.dict(os.environ, _portable_env(home_a, profile), clear=False):
                os.environ.pop("AG2C_DATA_ROOT", None)
                enroll_project(root, skill_root=skills, harnesses=("agents",))
                old_hooks = str(git(root, "config", "--get", "core.hooksPath")).strip()
                self.assertTrue(old_hooks.startswith(str(home_a)), old_hooks)
                self.assertTrue((home_a / "data" / "projects").is_dir())
                self.assertTrue(activation_status(root)["managed"])

            home_b = base / "portable-b"
            shutil.move(str(home_a), str(home_b))
            self.assertFalse(home_a.exists())

            with patch.dict(os.environ, _portable_env(home_b, profile), clear=False):
                os.environ.pop("AG2C_DATA_ROOT", None)
                status = activation_status(root)

                self.assertTrue(status["managed"], status["issues"])
                new_hooks = str(git(root, "config", "--get", "core.hooksPath")).strip()
                self.assertTrue(new_hooks.startswith(str(home_b)), new_hooks)
                self.assertTrue(Path(new_hooks).is_dir(), new_hooks)

                configured = str(git(root, "config", "--get", "ag2c.manifest")).strip()
                self.assertTrue(configured.startswith(str(home_b)), configured)

                registry = json.loads((home_b / "data" / "projects.json").read_text(encoding="utf-8"))
                self.assertEqual(str(home_b), str(registry.get("home") or ""))
                manifests = [str(item.get("manifest") or "") for item in registry["projects"]]
                self.assertTrue(manifests)
                for manifest in manifests:
                    self.assertTrue(manifest.startswith(str(home_b)), manifest)

                # The guard hook shim must call the runtime at the new location.
                shim = (Path(new_hooks) / "pre-commit").read_text(encoding="utf-8")
                self.assertNotIn(str(home_a), shim.replace("\\", "/"))

    def test_steady_portable_home_does_not_heal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = git_project(base / "demo")
            profile = base / "profile"
            profile.mkdir()
            home = base / "portable"
            home.mkdir()
            skills = base / "skills"
            with patch.dict(os.environ, _portable_env(home, profile), clear=False):
                os.environ.pop("AG2C_DATA_ROOT", None)
                enroll_project(root, skill_root=skills, harnesses=("agents",))
                with patch("ag2c.storage.heal_portable_move") as heal:
                    storage._read_registry()
                    heal.assert_not_called()
