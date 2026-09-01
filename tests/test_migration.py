from __future__ import annotations

import io
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import bootstrap

from ag2c.cli import main
from ag2c.config import discover_manifest
from ag2c.enrollment import activation_status, enroll_project, repair_project, setup_project, upgrade_project
from ag2c.errors import AG2CError, ConfigurationError, RELOCATED_PROJECT, STALE_EXTERNAL_STORE
from ag2c.gitops import git, status_entries
from ag2c.storage import (
    BINDING_RELOCATED,
    BINDING_STALE,
    configured_manifest,
    configured_project_key,
    project_key,
    project_store,
    resolve_enrollment_binding,
)

from support import git_project


def _point_git_at_foreign_store(root: Path, key: str, host: Path) -> Path:
    foreign = host / "Users" / "Old" / "AppData" / "Local" / "AutoGovern2Code" / "projects" / key / "manifest.json"
    hooks = foreign.parent / "state" / "hooks"
    git(root, "config", "--local", "ag2c.manifest", str(foreign))
    git(root, "config", "--local", "ag2c.project-key", key)
    git(root, "config", "--local", "core.hooksPath", str(hooks))
    return foreign


class CrossComputerMigrationTests(unittest.TestCase):
    def test_healthy_enroll_still_refuses_a_second_enroll(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "project")
            enroll_project(root, project_id="healthy-enroll", skill_root=workspace / "skills")
            with self.assertRaisesRegex(AG2CError, "already enrolled"):
                enroll_project(root, project_id="healthy-enroll", skill_root=workspace / "skills")

    def test_stale_foreign_manifest_is_reenrolled_on_this_computer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "project")
            first = enroll_project(root, project_id="stale-enroll", skill_root=workspace / "skills")
            store = Path(first["store"])
            shutil.rmtree(store)
            foreign = _point_git_at_foreign_store(root, "foreign-stale0000001", workspace)

            binding = resolve_enrollment_binding(root)
            self.assertEqual(BINDING_STALE, binding["state"])
            self.assertEqual(STALE_EXTERNAL_STORE, binding["code"])
            with self.assertRaisesRegex(ConfigurationError, STALE_EXTERNAL_STORE):
                discover_manifest(root)

            result = enroll_project(root, project_id="stale-enroll", skill_root=workspace / "skills")
            status = activation_status(root)
            rebound = configured_manifest(root)

            self.assertEqual("reenrolled", result["recovery"]["action"])
            self.assertEqual(STALE_EXTERNAL_STORE, result["recovery"]["code"])
            self.assertFalse(result["recovery"]["history_recovered"])
            self.assertEqual(str(foreign.resolve()), result["recovery"]["previous_manifest"])
            self.assertTrue(status["managed"], status)
            self.assertTrue(rebound is not None and rebound.is_file())
            self.assertTrue(str(rebound).replace("\\", "/").endswith("/projects/" + project_key(root) + "/manifest.json"))
            self.assertEqual([], status_entries(root))

    def test_dirty_stale_tree_does_not_clear_git_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "project")
            enroll_project(root, project_id="dirty-stale", skill_root=workspace / "skills")
            shutil.rmtree(project_store(root))
            foreign = _point_git_at_foreign_store(root, "foreign-aaaaaaaaaaaa", workspace)
            (root / "src" / "value.py").write_text("VALUE = 2\n", encoding="utf-8")

            with self.assertRaisesRegex(AG2CError, "commit or stash before enrolling"):
                enroll_project(root, project_id="dirty-stale", skill_root=workspace / "skills")
            self.assertEqual(foreign.resolve(), configured_manifest(root))
            self.assertEqual("foreign-aaaaaaaaaaaa", configured_project_key(root))

    def test_relocated_store_is_rebound_and_keeps_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "project")
            first = enroll_project(root, project_id="relocated-enroll", skill_root=workspace / "skills")
            key = first["project_key"]
            store = Path(first["store"])
            original_ledger = (store / "ledger.jsonl").read_text(encoding="utf-8")
            self.assertTrue(original_ledger.strip())
            _point_git_at_foreign_store(root, key, workspace)

            binding = resolve_enrollment_binding(root)
            self.assertEqual(BINDING_RELOCATED, binding["state"])
            self.assertEqual(RELOCATED_PROJECT, binding["code"])

            result = enroll_project(root, project_id="relocated-enroll", skill_root=workspace / "skills")
            status = activation_status(root)
            rebound = configured_manifest(root)

            self.assertEqual("rebound", result["action"])
            self.assertTrue(result["recovery"]["history_recovered"])
            self.assertEqual(key, result["project_key"])
            self.assertEqual(key, configured_project_key(root))
            self.assertEqual((store / "manifest.json").resolve(), rebound)
            self.assertTrue((store / "ledger.jsonl").read_text(encoding="utf-8").startswith(original_ledger))
            self.assertTrue(status["managed"], status)
            self.assertEqual([], status_entries(root))

    def test_copied_store_under_old_key_is_reused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "project")
            first = enroll_project(root, project_id="copied-key", skill_root=workspace / "skills")
            old_key = "foreign-copied0000001"
            old_store = project_store(root, old_key)
            shutil.copytree(first["store"], old_store)
            shutil.rmtree(first["store"])
            _point_git_at_foreign_store(root, old_key, workspace)

            result = upgrade_project(root, skill_root=workspace / "skills")
            self.assertEqual("rebound", result["action"])
            self.assertEqual(old_key, result["project_key"])
            self.assertEqual(old_key, configured_project_key(root))
            self.assertTrue((old_store / "manifest.json").is_file())
            self.assertTrue(activation_status(root)["managed"])

    def test_upgrade_and_repair_recover_a_missing_foreign_store(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "upgrade-project")
            enroll_project(root, project_id="upgrade-stale", skill_root=workspace / "skills")
            shutil.rmtree(project_store(root))
            _point_git_at_foreign_store(root, "foreign-bbbbbbbbbbbb", workspace)
            upgraded = upgrade_project(root, skill_root=workspace / "skills")
            self.assertEqual("reenrolled", upgraded["action"])
            self.assertTrue(activation_status(root)["managed"])

            other = git_project(workspace / "repair-project")
            enroll_project(other, project_id="repair-stale", skill_root=workspace / "skills")
            shutil.rmtree(project_store(other))
            _point_git_at_foreign_store(other, "foreign-cccccccccccc", workspace)
            repaired = repair_project(other, skill_root=workspace / "skills")
            self.assertEqual("repaired", repaired["action"])
            self.assertEqual(STALE_EXTERNAL_STORE, repaired["recovery"]["code"])
            self.assertTrue(activation_status(other)["managed"])

    def test_setup_recovers_stale_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "setup-project")
            enroll_project(root, project_id="setup-stale", skill_root=workspace / "skills")
            shutil.rmtree(project_store(root))
            _point_git_at_foreign_store(root, "foreign-dddddddddddd", workspace)
            setup = setup_project(root, project_id="setup-stale", skill_root=workspace / "skills")
            self.assertEqual("enrolled", setup["action"])
            self.assertFalse(setup["recovery"]["history_recovered"])
            self.assertTrue(activation_status(root)["managed"])

    def test_doctor_reports_stale_store_without_loading_the_old_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "doctor-project")
            enroll_project(root, project_id="doctor-stale", skill_root=workspace / "skills")
            shutil.rmtree(project_store(root))
            _point_git_at_foreign_store(root, "foreign-ffffffffffff", workspace)
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch_cwd(root), redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(["doctor"])
            self.assertEqual(1, code)
            self.assertIn(STALE_EXTERNAL_STORE, stdout.getvalue())
            self.assertNotIn("does not exist", stderr.getvalue())


class patch_cwd:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.previous = Path.cwd()

    def __enter__(self):
        import os

        os.chdir(self.path)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        import os

        os.chdir(self.previous)


if __name__ == "__main__":
    unittest.main()
