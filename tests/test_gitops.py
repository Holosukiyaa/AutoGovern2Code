from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bootstrap

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

    def test_system_git_is_preferred_when_source_is_unset(self) -> None:
        real = shutil.which("git")
        self.assertIsNotNone(real)
        with tempfile.TemporaryDirectory() as directory:
            bundled, _fake = _fake_bundled_git(directory)
            with patch.dict(os.environ, {"AG2C_GIT": "", "AG2C_GIT_ROOT": str(bundled)}, clear=False):
                self.assertEqual(Path(git_executable()).resolve(), Path(real).resolve())

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

    def test_first_use_records_system_git_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = git_project(Path(directory) / "project")
            git(project, "status")
            self.assertEqual(GIT_SOURCE_SYSTEM, read_local_git_source(project))

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
