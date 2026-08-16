from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bootstrap

import ag2c.enrollment as enrollment_module
from ag2c.enrollment import activation_status, enroll_project, migrate_project, upgrade_project
from ag2c.errors import AG2CError
from ag2c.gitops import git, status_entries
from ag2c.ledger import verify_ledger
from ag2c.lifecycle import LifecycleTransaction, recover_lifecycle

from support import git_project


class LifecycleTests(unittest.TestCase):
    def test_enrollment_commit_failure_rolls_back_everything(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "project")
            before_head = str(git(root, "rev-parse", "HEAD")).strip()
            before_ignore = (root / ".gitignore").read_bytes()
            real_git = enrollment_module.git

            def fail_commit(repository: Path, *args: str, **kwargs):
                if args and args[0] == "commit":
                    raise AG2CError("injected enrollment commit failure")
                return real_git(repository, *args, **kwargs)

            with patch("ag2c.enrollment.git", side_effect=fail_commit):
                with self.assertRaisesRegex(AG2CError, "injected enrollment commit failure"):
                    enroll_project(root, project_id="rollback-enrollment", skill_root=workspace / "skills")

            self.assertEqual(before_head, str(git(root, "rev-parse", "HEAD")).strip())
            self.assertEqual(before_ignore, (root / ".gitignore").read_bytes())
            self.assertFalse((root / "AGENTS.md").exists())
            self.assertFalse((root / "CLAUDE.md").exists())
            self.assertFalse((root / ".ag2c").exists())
            self.assertEqual([], status_entries(root))

    def test_upgrade_refreshes_ag2c_managed_baseline_areas(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "project")
            enroll_project(root, project_id="upgrade-project", skill_root=workspace / "skills")
            (root / "docs").mkdir()
            (root / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
            git(root, "add", "docs/guide.md")
            git(root, "-c", "core.hooksPath=", "commit", "-m", "docs: add project area")

            result = upgrade_project(root, skill_root=workspace / "skills")
            self.assertEqual("upgraded", result["action"])
            policy = json.loads((root / ".ag2c" / "policy.json").read_text(encoding="utf-8"))
            self.assertIn("docs", policy["coverage"]["areas"])
            self.assertIn("floor.docs", {card["id"] for card in policy["cards"]})
            self.assertEqual([], status_entries(root))
            self.assertEqual("chore: upgrade AG2C to 0.5.0", str(git(root, "log", "-1", "--pretty=%s")).strip())

    def test_upgrade_failure_restores_files_staging_and_head(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "project")
            enroll_project(root, project_id="rollback-project", skill_root=workspace / "skills")
            before_head = str(git(root, "rev-parse", "HEAD")).strip()
            before = {
                path: (root / path).read_bytes()
                for path in ("AGENTS.md", "CLAUDE.md", ".gitignore", ".ag2c/enrollment.json", ".ag2c/policy.json")
            }

            with patch("ag2c.enrollment._maintenance_commit", side_effect=AG2CError("injected failure")):
                with self.assertRaisesRegex(AG2CError, "injected failure"):
                    upgrade_project(root, skill_root=workspace / "skills")

            self.assertEqual(before_head, str(git(root, "rev-parse", "HEAD")).strip())
            self.assertEqual([], status_entries(root))
            for path, content in before.items():
                self.assertEqual(content, (root / path).read_bytes(), path)

    def test_interrupted_lifecycle_is_recovered_on_next_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = git_project(Path(directory) / "工程 with spaces")
            original = (root / ".gitignore").read_bytes()
            transaction = LifecycleTransaction(root, "test-interruption", [".gitignore"])
            transaction.__enter__()
            (root / ".gitignore").write_text("interrupted\n", encoding="utf-8")

            recovery = recover_lifecycle(root)

            self.assertEqual("rolled-back", recovery["action"])
            self.assertEqual(original, (root / ".gitignore").read_bytes())
            self.assertEqual([], status_entries(root))

    def test_migrates_legacy_deg_without_rewriting_old_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "project")
            legacy = root / ".deg"
            legacy.mkdir()
            manifest = {
                "schema": "deg.manifest.v1",
                "project": {"id": "legacy-project"},
                "policy": ".deg/policy.json",
                "state_dir": ".deg/state",
                "ledger": ".deg/ledger.jsonl",
                "targets": [
                    {
                        "id": "app",
                        "path": ".",
                        "governed_roots": ["."],
                        "exclude": [".deg/state/**", ".deg/ledger.jsonl", ".deg/ledger.jsonl.lock"],
                    }
                ],
            }
            policy = {
                "schema": "deg.policy.v1",
                "cards": [
                    {
                        "id": "constitution.project",
                        "type": "constitution",
                        "title": "DEG project invariants",
                        "summary": "DEG controls engineering changes.",
                        "references": ["AGENTS.md"],
                    },
                    {
                        "id": "floor.project",
                        "type": "floor",
                        "title": "Project implementation",
                        "summary": "Owns the complete project.",
                        "scopes": [{"target": "app", "include": ["**"], "ownership": "primary"}],
                        "checkers": ["check.python"],
                    },
                ],
                "relations": [],
                "contracts": [],
                "checkers": [
                    {
                        "id": "check.python",
                        "stage": "floor",
                        "target": "app",
                        "command": ["python", "-m", "unittest", "discover", "-s", "tests"],
                        "cwd": ".",
                        "timeout": 900,
                    }
                ],
            }
            enrollment = {
                "schema": "deg.enrollment.v1",
                "project_id": "legacy-project",
                "enrolled_at": "2026-08-15T00:00:00+00:00",
                "skill": "deg-governed-development",
            }
            for name, value in (("manifest.json", manifest), ("policy.json", policy), ("enrollment.json", enrollment)):
                (legacy / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
            old_ledger = b"legacy evidence remains byte-for-byte intact\n"
            (legacy / "ledger.jsonl").write_bytes(old_ledger)
            legacy_notes = b"project-specific legacy governance notes\n"
            (legacy / "notes.txt").write_bytes(legacy_notes)
            (root / "AGENTS.md").write_text(
                "<!-- DEG:BEGIN -->\n# DEG governed engineering\n<!-- DEG:END -->\n",
                encoding="utf-8",
            )
            with (root / ".gitignore").open("a", encoding="utf-8") as handle:
                handle.write("\n# DEG:BEGIN\n.deg/state/\n.deg/ledger.jsonl\n# DEG:END\n")
            git(root, "add", "AGENTS.md", ".gitignore", ".deg/manifest.json", ".deg/policy.json", ".deg/enrollment.json", ".deg/notes.txt")
            git(root, "commit", "-m", "chore: enroll legacy DEG")

            result = migrate_project(root, skill_root=workspace / "skills")
            self.assertEqual("migrated", result["action"])
            self.assertFalse(legacy.exists())
            self.assertTrue(activation_status(root)["managed"])
            self.assertEqual([], status_entries(root))
            migrated_policy = json.loads((root / ".ag2c" / "policy.json").read_text(encoding="utf-8"))
            self.assertEqual("baseline", migrated_policy["coverage"]["level"])
            python_checker = next(item for item in migrated_policy["checkers"] if item["id"] == "check.python")
            self.assertEqual("-B", python_checker["command"][1])
            archived = Path(result["legacy_archive"]) / "ledger.jsonl"
            self.assertEqual(old_ledger, archived.read_bytes())
            self.assertEqual(legacy_notes, (Path(result["legacy_archive"]) / "notes.txt").read_bytes())
            self.assertTrue((Path(result["legacy_archive"]) / "manifest.json").is_file())
            self.assertEqual(hashlib.sha256(old_ledger).hexdigest(), result["legacy_ledger_digest"])
            self.assertEqual([], verify_ledger(root / ".ag2c" / "ledger.jsonl"))
            self.assertEqual("chore: migrate DEG to AutoGovern2Code", str(git(root, "log", "-1", "--pretty=%s")).strip())


if __name__ == "__main__":
    unittest.main()
