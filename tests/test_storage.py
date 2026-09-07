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
from ag2c.enrollment import enroll_project
from ag2c.gitops import git


class PortableMoveTests(unittest.TestCase):
    def test_moving_portable_home_rebases_registry_and_rebinds_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = git_project(base / "demo")
            home_a = base / "portable-a"
            home_a.mkdir()
            skills = base / "skills"
            env = {name: "" for name in ("AG2C_DATA_ROOT", "AG2C_GIT", "AG2C_GIT_ROOT")}
            with patch.dict(os.environ, {**env, "AG2C_PORTABLE": str(home_a)}, clear=False):
                os.environ.pop("AG2C_DATA_ROOT", None)
                result = enroll_project(root, skill_root=skills, harnesses=("agents",))
                old_hooks = str(git(root, "config", "--get", "core.hooksPath")).strip()
                self.assertTrue(old_hooks.startswith(str(home_a)), old_hooks)
                self.assertTrue((home_a / "data" / "projects").is_dir())

            home_b = base / "portable-b"
            shutil.move(str(home_a), str(home_b))
            self.assertFalse((home_a).exists())

            with patch.dict(os.environ, {**env, "AG2C_PORTABLE": str(home_b)}, clear=False):
                os.environ.pop("AG2C_DATA_ROOT", None)
                registry = storage._read_registry()

                self.assertEqual(str(home_b), str(registry.get("home") or ""))
                manifests = [str(item.get("manifest") or "") for item in registry["projects"]]
                self.assertTrue(manifests)
                for manifest in manifests:
                    self.assertTrue(manifest.startswith(str(home_b)), manifest)
                    self.assertTrue(Path(manifest).is_file(), manifest)

                new_hooks = str(git(root, "config", "--get", "core.hooksPath")).strip()
                self.assertTrue(new_hooks.startswith(str(home_b)), new_hooks)
                self.assertTrue(Path(new_hooks).is_dir(), new_hooks)

                # The registry on disk must be healed too, not just the return value.
                on_disk = json.loads((home_b / "data" / "projects.json").read_text(encoding="utf-8"))
                self.assertEqual(str(home_b), str(on_disk.get("home") or ""))

    def test_steady_portable_home_does_not_rebind(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = git_project(base / "demo")
            home = base / "portable"
            home.mkdir()
            skills = base / "skills"
            env = {"AG2C_PORTABLE": str(home)}
            with patch.dict(os.environ, env, clear=False):
                os.environ.pop("AG2C_DATA_ROOT", None)
                enroll_project(root, skill_root=skills, harnesses=("agents",))
                with patch("ag2c.storage.rebind_portable_git_enrollment") as rebind:
                    storage._read_registry()
                    rebind.assert_not_called()


if __name__ == "__main__":
    unittest.main()
