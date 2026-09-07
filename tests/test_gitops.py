from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bootstrap
from support import git_project, _git

from ag2c.errors import GIT_MISSING, AG2CError
from ag2c.gitops import (
    GIT_SOURCE_BUNDLED,
    GIT_SOURCE_SYSTEM,
    change_digest,
    commit_change_digest,
    git,
    git_executable,
    head,
    read_local_git_source,
    seize_existing_git,
    shipped_git_executable,
)

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

    def test_many_changed_files_match_committed_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = git_project(Path(directory) / "project")
            git(root, "commit", "--allow-empty", "-m", "base")
            base = head(root)
            for index in range(40):
                (root / f"page-{index}.html").write_text(f"<p>{index}</p>\n", encoding="utf-8")

            worktree_digest = change_digest(root, base)
            git(root, "add", ".")
            git(root, "commit", "-m", "add pages")

            self.assertEqual(worktree_digest, commit_change_digest(root, base, head(root)))


def _fake_bundled_git(directory: str) -> tuple[Path, Path]:
    root = Path(directory)
    cmd = root / "cmd"
    cmd.mkdir(parents=True, exist_ok=True)
    fake = cmd / ("git.exe" if os.name == "nt" else "git")
    fake.write_bytes(b"")
    return root, fake


def _write_git_source(project: Path, source: str) -> None:
    config = project / ".git" / "config"
    text = config.read_text(encoding="utf-8")
    if "[ag2c]" not in text:
        text += f"\n[ag2c]\n\tgit-source = {source}\n"
    config.write_text(text, encoding="utf-8")


class GitExecutableTests(unittest.TestCase):
    def test_ag2c_git_override_is_used(self) -> None:
        real = shutil.which("git")
        self.assertIsNotNone(real)
        with patch.dict(os.environ, {"AG2C_GIT": real, "AG2C_GIT_ROOT": ""}, clear=False):
            self.assertEqual(Path(git_executable()).resolve(), Path(real).resolve())

    def test_portable_git_wins_over_system_git(self) -> None:
        real = shutil.which("git")
        self.assertIsNotNone(real)
        with tempfile.TemporaryDirectory() as directory:
            bundled, fake = _fake_bundled_git(str(Path(directory) / "portable"))
            with patch.dict(os.environ, {"AG2C_GIT": "", "AG2C_GIT_ROOT": "", "AG2C_PORTABLE_GIT": str(bundled)}, clear=False):
                self.assertEqual(Path(git_executable()).resolve(), fake.resolve())
                self.assertEqual(Path(shipped_git_executable()).resolve(), fake.resolve())
                self.assertNotEqual(Path(git_executable()).resolve(), Path(real).resolve())

    def test_bundled_git_is_preferred_when_present(self) -> None:
        real = shutil.which("git")
        self.assertIsNotNone(real)
        with tempfile.TemporaryDirectory() as directory:
            bundled, fake = _fake_bundled_git(directory)
            with patch.dict(os.environ, {"AG2C_GIT": "", "AG2C_GIT_ROOT": str(bundled), "AG2C_PORTABLE_GIT": ""}, clear=False):
                self.assertEqual(Path(git_executable()).resolve(), fake.resolve())
                self.assertNotEqual(Path(git_executable()).resolve(), Path(real).resolve())

    def test_sticky_bundled_source_keeps_bundled_git(self) -> None:
        real = shutil.which("git")
        self.assertIsNotNone(real)
        with tempfile.TemporaryDirectory() as directory:
            project = git_project(Path(directory) / "project")
            _write_git_source(project, GIT_SOURCE_BUNDLED)
            bundled, fake = _fake_bundled_git(str(Path(directory) / "mingit"))
            with patch.dict(os.environ, {"AG2C_GIT": "", "AG2C_GIT_ROOT": str(bundled)}, clear=False):
                self.assertEqual(Path(git_executable(project)).resolve(), fake.resolve())
                self.assertNotEqual(Path(git_executable(project)).resolve(), Path(real).resolve())

    def test_sticky_system_source_falls_back_to_bundled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = git_project(Path(directory) / "project")
            _write_git_source(project, GIT_SOURCE_SYSTEM)
            bundled, fake = _fake_bundled_git(str(Path(directory) / "mingit"))
            with patch.dict(os.environ, {"AG2C_GIT": "", "AG2C_GIT_ROOT": str(bundled)}, clear=False):
                with patch("ag2c.gitops.system_git_executable", return_value=None):
                    self.assertEqual(Path(git_executable(project)).resolve(), fake.resolve())

    def test_first_use_records_system_git_source_when_only_system_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = git_project(Path(directory) / "project")
            with patch.dict(os.environ, {"AG2C_GIT": "", "AG2C_GIT_ROOT": "", "AG2C_PORTABLE_GIT": ""}, clear=False):
                git(project, "status")
            self.assertEqual(GIT_SOURCE_SYSTEM, read_local_git_source(project))

    def test_seize_keeps_history_and_records_bundled_git(self) -> None:
        real = shutil.which("git")
        self.assertIsNotNone(real)
        with tempfile.TemporaryDirectory() as directory:
            project = git_project(Path(directory) / "project")
            before = (project / ".git" / "HEAD").read_text(encoding="utf-8")
            bundled, fake = _fake_bundled_git(str(Path(directory) / "mingit"))
            with patch.dict(os.environ, {"AG2C_GIT": "", "AG2C_GIT_ROOT": str(bundled), "AG2C_PORTABLE_GIT": ""}, clear=False):
                seized = seize_existing_git(project)
            self.assertEqual(Path(seized).resolve(), fake.resolve())
            self.assertEqual(GIT_SOURCE_BUNDLED, read_local_git_source(project))
            self.assertEqual(before, (project / ".git" / "HEAD").read_text(encoding="utf-8"))
            self.assertTrue((project / ".git").is_dir())

    def test_missing_git_is_a_named_error(self) -> None:
        with patch.dict(
            os.environ,
            {"AG2C_GIT": "", "AG2C_GIT_ROOT": "", "AG2C_SKIP_GIT_DOWNLOAD": "1"},
            clear=False,
        ):
            with patch("ag2c.gitops.system_git_executable", return_value=None):
                with patch("ag2c.gitops.bundled_git_root", return_value=None):
                    with self.assertRaises(AG2CError) as raised:
                        git_executable()
                    self.assertEqual(GIT_MISSING, raised.exception.code)


class PortableLayoutTests(unittest.TestCase):
    def test_portable_env_puts_data_next_to_the_folder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "portable"
            home.mkdir()
            (home / "portable.ini").write_text("home=.\n", encoding="utf-8")
            with patch.dict(os.environ, {"AG2C_PORTABLE": str(home), "AG2C_DATA_ROOT": ""}, clear=False):
                from ag2c.util import default_data_root, portable_home

                self.assertEqual(home.resolve(), portable_home())
                self.assertEqual((home / "data").resolve(), default_data_root())

    def test_moved_portable_folder_rebases_store_paths_not_project_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            old_home = Path(directory) / "old"
            new_home = Path(directory) / "new"
            old_home.mkdir()
            new_home.mkdir()
            (new_home / "portable.ini").write_text("home=.\n", encoding="utf-8")
            old_manifest = old_home / "data" / "projects" / "demo" / "manifest.json"
            new_manifest = new_home / "data" / "projects" / "demo" / "manifest.json"
            new_manifest.parent.mkdir(parents=True)
            new_manifest.write_text("{}", encoding="utf-8")
            with patch.dict(os.environ, {"AG2C_PORTABLE": str(new_home), "AG2C_DATA_ROOT": ""}, clear=False):
                from ag2c.storage import _read_registry, registry_path

                path = registry_path()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(
                        {
                            "schema": "ag2c.registry.v1",
                            "home": str(old_home),
                            "projects": [
                                {
                                    "key": "demo",
                                    "name": "Demo",
                                    "root": r"C:\Work\Demo",
                                    "manifest": str(old_manifest),
                                    "governance": "active",
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                records = _read_registry()["projects"]
                self.assertEqual(r"C:\Work\Demo", records[0]["root"])
                self.assertEqual(str(new_manifest.resolve()), str(Path(records[0]["manifest"]).resolve()))

    def test_checkout_portable_ini_sends_archive_next_to_the_app(self) -> None:
        root = Path(__file__).resolve().parents[1]
        ignore = (root / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("/portable.ini", ignore)
        self.assertIn(".grok/", ignore)
        if not (root / "portable.ini").is_file():
            self.skipTest("portable.ini lives on the operator checkout, not a task worktree")
        ignored = git(root, "check-ignore", "portable.ini", ".grok/session.md")
        self.assertIn("portable.ini", ignored)
        self.assertIn(".grok/session.md", ignored.replace("\\", "/"))
        with patch.dict(os.environ, {"AG2C_PORTABLE": "", "AG2C_DATA_ROOT": ""}, clear=False):
            from ag2c.util import default_data_root, portable_home

            home = portable_home()
            self.assertEqual(root.resolve(), home)
            self.assertEqual((root / "data").resolve(), default_data_root())

    def test_adopt_installed_archive_copies_projects_not_webview(self) -> None:
        from ag2c.storage import adopt_installed_archive

        with tempfile.TemporaryDirectory() as directory:
            origin = Path(directory) / "installed"
            portable = Path(directory) / "portable"
            pack = portable / "data"
            store = origin / "projects" / "demo-key"
            store.mkdir(parents=True)
            manifest = store / "manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            (store / "ledger.jsonl").write_text("{}\n", encoding="utf-8")
            bulky = store / "worktrees" / "task-1" / "src"
            bulky.mkdir(parents=True)
            (bulky / "blob.bin").write_bytes(b"x" * 1024)
            (origin / "webview2").mkdir()
            (origin / "webview2" / "junk.bin").write_text("no", encoding="utf-8")
            (origin / "projects.json").write_text(
                json.dumps(
                    {
                        "schema": "ag2c.registry.v1",
                        "projects": [
                            {
                                "key": "demo-key",
                                "name": "Demo",
                                "root": r"C:\Work\Demo",
                                "manifest": str(manifest),
                                "governance": "active",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"AG2C_PORTABLE": str(portable), "AG2C_DATA_ROOT": str(pack)}, clear=False):
                first = adopt_installed_archive(dest=pack, source=origin)
                second = adopt_installed_archive(dest=pack, source=origin)
            self.assertEqual("adopted", first["action"])
            self.assertEqual(1, first["projects"])
            self.assertEqual("keep", second["action"])
            registry = json.loads((pack / "projects.json").read_text(encoding="utf-8"))
            self.assertEqual(r"C:\Work\Demo", registry["projects"][0]["root"])
            self.assertEqual(str((pack / "projects" / "demo-key" / "manifest.json").resolve()), str(Path(registry["projects"][0]["manifest"]).resolve()))
            self.assertTrue((pack / "projects" / "demo-key" / "ledger.jsonl").is_file())
            self.assertFalse((pack / "webview2").exists())
            self.assertFalse((pack / "projects" / "demo-key" / "worktrees").exists())

    def test_rebind_portable_git_points_at_pack_not_appdata(self) -> None:
        from ag2c.storage import rebind_portable_git_enrollment, _write_registry

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repo = git_project(base / "repo")
            portable = base / "portable"
            pack = portable / "data"
            store = pack / "projects" / "demo-key"
            hooks = store / "state" / "hooks"
            hooks.mkdir(parents=True)
            (hooks / "pre-commit").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            manifest = store / "manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            _git(repo, "config", "ag2c.manifest", r"C:\Users\Holo\AppData\Local\AutoGovern2Code\projects\demo-key\manifest.json")
            _git(repo, "config", "core.hooksPath", r"C:\Users\Holo\AppData\Local\AutoGovern2Code\projects\demo-key\state\hooks")
            with patch.dict(os.environ, {"AG2C_PORTABLE": str(portable), "AG2C_DATA_ROOT": str(pack)}, clear=False):
                (portable / "portable.ini").write_text("home=.\n", encoding="utf-8")
                _write_registry(
                    {
                        "schema": "ag2c.registry.v1",
                        "projects": [
                            {
                                "key": "demo-key",
                                "root": str(repo),
                                "manifest": str(manifest),
                                "name": "Demo",
                                "governance": "active",
                            }
                        ],
                    }
                )
                bound = rebind_portable_git_enrollment()
            self.assertEqual(1, len(bound))
            pointed = _git(repo, "config", "--local", "--get", "ag2c.manifest")
            self.assertEqual(str(manifest.resolve()), pointed)
            self.assertEqual(str(hooks.resolve()), _git(repo, "config", "--local", "--get", "core.hooksPath"))
            self.assertTrue(pointed.replace("\\", "/").endswith("/portable/data/projects/demo-key/manifest.json"))

    def test_relocate_installed_worktree_into_portable_pack(self) -> None:
        from ag2c.storage import _write_registry, relocate_installed_worktrees

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repo = git_project(base / "repo")
            portable = base / "portable"
            pack = portable / "data"
            local = base / "Local"
            origin = local / "AutoGovern2Code"
            old_wt = origin / "projects" / "demo-key" / "worktrees" / "task-1"
            old_wt.parent.mkdir(parents=True)
            _git(repo, "worktree", "add", "-b", "ag2c/task-1", str(old_wt), "HEAD")
            store = pack / "projects" / "demo-key"
            tasks = store / "state" / "tasks"
            tasks.mkdir(parents=True)
            (store / "manifest.json").write_text("{}", encoding="utf-8")
            (tasks / "task-1.json").write_text(
                json.dumps(
                    {
                        "schema": "ag2c.task.v1",
                        "id": "task-1",
                        "worktree": {"path": str(old_wt), "branch": "ag2c/task-1"},
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "AG2C_PORTABLE": str(portable),
                    "AG2C_DATA_ROOT": str(pack),
                    "LOCALAPPDATA": str(local),
                },
                clear=False,
            ):
                (portable / "portable.ini").write_text("home=.\n", encoding="utf-8")
                _write_registry(
                    {
                        "schema": "ag2c.registry.v1",
                        "projects": [
                            {
                                "key": "demo-key",
                                "root": str(repo),
                                "manifest": str(store / "manifest.json"),
                                "name": "Demo",
                                "governance": "active",
                            }
                        ],
                    }
                )
                moved = relocate_installed_worktrees()
            dest = pack / "projects" / "demo-key" / "worktrees" / "task-1"
            self.assertTrue(dest.is_dir())
            self.assertFalse(old_wt.is_dir())
            self.assertEqual(1, len(moved))
            listing = _git(repo, "worktree", "list")
            self.assertTrue(str(dest) in listing or str(dest).replace("\\", "/") in listing.replace("\\", "/"))
            task = json.loads((tasks / "task-1.json").read_text(encoding="utf-8"))
            self.assertEqual(str(dest.resolve()), str(Path(task["worktree"]["path"]).resolve()))
