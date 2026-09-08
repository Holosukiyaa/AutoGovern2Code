"""Sunset clause and canary tests."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ag2c.checks import load_test_baseline, _save_test_baseline
from ag2c.households import expired_renewals, load_renewals, RENEWAL_SCHEMA, RENEWAL_FILENAME
from ag2c.model import Manifest


def _manifest(root: Path) -> Manifest:
    return Manifest(
        path=root / "manifest.json",
        project_id="test-proj",
        project_root=root,
        targets=[],
        ledger_path=root / "ledger.jsonl",
        policy_path=root / "policy.json",
        state_dir=root / "state",
    )


class SunsetRenewalTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp())
        self._manifest = _manifest(self._tmp)
        (self._tmp / "state").mkdir(parents=True, exist_ok=True)

    def test_no_renewals_no_expired(self) -> None:
        self.assertEqual([], expired_renewals(self._manifest))

    def test_fresh_renewal_not_expired(self) -> None:
        cards = {
            "knowledge.a": {
                "renewed_at": datetime.now(timezone.utc).isoformat(),
                "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
                "actor": "test",
                "reason": "test",
                "child_directories": [],
            }
        }
        path = self._tmp / "state" / RENEWAL_FILENAME
        path.write_text(json.dumps({"schema": RENEWAL_SCHEMA, "cards": cards}), encoding="utf-8")
        self.assertEqual([], expired_renewals(self._manifest))

    def test_expired_renewal_detected(self) -> None:
        cards = {
            "knowledge.old": {
                "renewed_at": (datetime.now(timezone.utc) - timedelta(days=60)).isoformat(),
                "expires_at": (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),
                "actor": "test",
                "reason": "test",
                "child_directories": [],
            }
        }
        path = self._tmp / "state" / RENEWAL_FILENAME
        path.write_text(json.dumps({"schema": RENEWAL_SCHEMA, "cards": cards}), encoding="utf-8")
        self.assertEqual(["knowledge.old"], expired_renewals(self._manifest))

    def test_legacy_record_without_expires_still_valid(self) -> None:
        cards = {
            "knowledge.legacy": {
                "renewed_at": datetime.now(timezone.utc).isoformat(),
                "actor": "test",
                "reason": "test",
                "child_directories": [],
            }
        }
        path = self._tmp / "state" / RENEWAL_FILENAME
        path.write_text(json.dumps({"schema": RENEWAL_SCHEMA, "cards": cards}), encoding="utf-8")
        self.assertEqual([], expired_renewals(self._manifest))


class SunsetBaselineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp())
        self._manifest = _manifest(self._tmp)
        (self._tmp / "state").mkdir(parents=True, exist_ok=True)

    def test_fresh_baseline_loaded(self) -> None:
        _save_test_baseline(
            self._manifest,
            {"check.python": ["test_a", "test_b"]},
            actor="test",
            reason="test",
        )
        baseline = load_test_baseline(self._manifest)
        self.assertEqual(["test_a", "test_b"], baseline["check.python"])

    def test_expired_baseline_not_loaded(self) -> None:
        # Write a baseline with an expired expires_at directly.
        path = self._tmp / "state" / "test-baseline.json"
        expired = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        payload = {
            "schema": "ag2c.test-baseline.v1",
            "checkers": {
                "check.python": {
                    "failures": ["test_a"],
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "expires_at": expired,
                    "actor": "test",
                }
            },
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        baseline = load_test_baseline(self._manifest)
        self.assertEqual({}, baseline)

    def test_baseline_without_expires_still_loaded(self) -> None:
        # Legacy baseline without expires_at should still work.
        path = self._tmp / "state" / "test-baseline.json"
        payload = {
            "schema": "ag2c.test-baseline.v1",
            "checkers": {
                "check.python": {
                    "failures": ["test_a"],
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "actor": "test",
                }
            },
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        baseline = load_test_baseline(self._manifest)
        self.assertEqual(["test_a"], baseline["check.python"])

    def test_save_includes_expires_at(self) -> None:
        _save_test_baseline(
            self._manifest,
            {"check.python": ["test_a"]},
            actor="test",
            reason="test",
        )
        path = self._tmp / "state" / "test-baseline.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        record = raw["checkers"]["check.python"]
        self.assertIn("expires_at", record)
        expires = datetime.fromisoformat(record["expires_at"])
        self.assertGreater(expires, datetime.now(timezone.utc))


def _canary_project(root: Path):
    """Minimal governed project whose always-on checker runs unittest discovery."""
    (root / ".ag2c" / "state").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "src" / "value.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests" / "test_value.py").write_text(
        "import unittest\n\n"
        "class ValueTests(unittest.TestCase):\n"
        "    def test_value(self):\n"
        "        self.assertEqual(1, 1)\n",
        encoding="utf-8",
    )
    manifest = {
        "schema": "ag2c.manifest.v1",
        "project": {"id": "canary-project"},
        "policy": ".ag2c/policy.json",
        "state_dir": ".ag2c/state",
        "ledger": ".ag2c/ledger.jsonl",
        "targets": [
            {"id": "app", "path": ".", "governed_roots": ["src", "tests"], "exclude": []}
        ],
    }
    policy = {
        "schema": "ag2c.policy.v1",
        "cards": [
            {"id": "constitution.project", "type": "constitution", "title": "C", "summary": "S"},
            {
                "id": "floor.tests",
                "type": "floor",
                "title": "Tests",
                "summary": "Owns tests.",
                "scopes": [{"target": "app", "include": ["tests/**"], "ownership": "primary"}],
                "checkers": ["check.python"],
            },
            {
                "id": "floor.src",
                "type": "floor",
                "title": "Src",
                "summary": "Owns src.",
                "scopes": [{"target": "app", "include": ["src/**"], "ownership": "primary"}],
                "checkers": ["check.noop"],
            },
        ],
        "relations": [],
        "contracts": [],
        "checkers": [
            {
                "id": "check.python",
                "stage": "floor",
                "target": "app",
                "command": [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests"],
                "cwd": ".",
                "timeout": 120,
                "always": True,
                "parse": "unittest",
            },
            {
                "id": "check.noop",
                "stage": "floor",
                "target": "app",
                "command": [sys.executable, "-c", "print('noop')"],
                "cwd": ".",
                "timeout": 30,
            },
        ],
    }
    (root / ".ag2c" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / ".ag2c" / "policy.json").write_text(json.dumps(policy), encoding="utf-8")
    from ag2c.config import load_manifest, load_policy

    loaded = load_manifest(root / ".ag2c" / "manifest.json")
    return loaded, load_policy(loaded)


class CanaryEndToEndTests(unittest.TestCase):
    """The canary must run end to end: plant, refresh, gate catches, cleanup."""

    def test_canary_caught_and_cleaned_up(self) -> None:
        from ag2c.cli import _canary
        from ag2c.index import build_index, verify_freshness

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, policy = _canary_project(root)
            build_index(manifest, policy)
            exit_code = _canary(manifest, policy, actor="test", reason="e2e gate validation")
            self.assertEqual(0, exit_code)
            # Canary file removed and index snapshot restored.
            self.assertFalse((root / "tests" / "test_ag2c_canary.py").exists())
            self.assertEqual([], verify_freshness(manifest, policy))
            events = [
                json.loads(line)
                for line in (root / ".ag2c" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            canary_events = [e for e in events if e.get("event_type") == "canary"]
            self.assertEqual(1, len(canary_events))
            payload = canary_events[0]["payload"]
            self.assertEqual("passed", payload["canary"])
            self.assertIn("check.python", payload["caught_by"])

    def test_canary_refuses_without_tests_dir(self) -> None:
        from ag2c.cli import _canary

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, policy = _canary_project(root)
            shutil.rmtree(root / "tests")
            self.assertEqual(2, _canary(manifest, policy, actor="test", reason="no tests dir"))


if __name__ == "__main__":
    unittest.main()
