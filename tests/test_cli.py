from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import bootstrap

from ag2c.cli import main
from ag2c.config import discover_manifest
from ag2c.gitops import status_entries

from support import git_project


class CLITests(unittest.TestCase):
    def test_explicit_external_manifest_keeps_its_declared_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = git_project(Path(directory) / "repository")
            nested = root / "example"
            (nested / "src").mkdir(parents=True)
            (nested / "src" / "value.py").write_text("VALUE = 1\n", encoding="utf-8")
            config = root / "governance"
            config.mkdir()
            manifest = {
                "schema": "ag2c.manifest.v1",
                "project": {"id": "nested-example", "root": "../example"},
                "policy": "policy.json",
                "state_dir": "state",
                "ledger": "ledger.jsonl",
                "targets": [{"id": "app", "path": ".", "governed_roots": ["src"], "exclude": []}],
            }
            policy = {
                "schema": "ag2c.policy.v1",
                "cards": [{
                    "id": "floor.app",
                    "type": "floor",
                    "title": "App",
                    "summary": "Owns the fixture.",
                    "scopes": [{"target": "app", "include": ["src/**"], "exclude": [], "ownership": "primary"}],
                    "checkers": ["check.app"],
                    "references": [],
                }],
                "relations": [],
                "contracts": [],
                "checkers": [{"id": "check.app", "stage": "floor", "target": "app", "command": ["python", "-B", "-c", "print('ok')"], "cwd": ".", "timeout": 30}],
            }
            (config / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (config / "policy.json").write_text(json.dumps(policy), encoding="utf-8")
            previous = Path.cwd()
            output = io.StringIO()
            try:
                os.chdir(nested)
                with redirect_stdout(output):
                    self.assertEqual(0, main(["--manifest", str(config / "manifest.json"), "index", "build"]))
            finally:
                os.chdir(previous)
            self.assertIn(str(config / "state" / "index.sqlite"), output.getvalue())

    def test_enroll_installs_automatic_governance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "project")
            with patch("ag2c.enrollment.Path.home", return_value=workspace):
                self.assertEqual(main(["enroll", str(root), "--project-id", "starter"]), 0)
                previous = Path.cwd()
                try:
                    os.chdir(root)
                    self.assertEqual(main(["guard", "status"]), 0)
                finally:
                    os.chdir(previous)
            manifest = discover_manifest(root)
            self.assertTrue((manifest.parent / "enrollment.json").is_file())
            self.assertFalse((root / ".ag2c").exists())
            self.assertFalse((root / "AGENTS.md").exists())
            self.assertFalse((root / "CLAUDE.md").exists())
            self.assertEqual([], status_entries(root))
            self.assertTrue((workspace / ".codex" / "skills" / "ag2c-governed-development" / "SKILL.md").is_file())
            self.assertTrue((workspace / ".claude" / "skills" / "ag2c-governed-development" / "SKILL.md").is_file())
            self.assertTrue((workspace / ".agents" / "skills" / "ag2c-governed-development" / "SKILL.md").is_file())


if __name__ == "__main__":
    unittest.main()
