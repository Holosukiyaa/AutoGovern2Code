"""Tests for task helpers (finish hints)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import bootstrap

from ag2c.model import Manifest
from ag2c.tasks import _finish_hints

from support import write_project


def _bare_manifest(root: Path) -> Manifest:
    return Manifest(
        path=root / "manifest.json",
        project_id="test-proj",
        project_root=root,
        targets=[],
        ledger_path=root / "ledger.jsonl",
        policy_path=root / "policy.json",
        state_dir=root / "state",
    )


class FinishHintTests(unittest.TestCase):
    def test_pending_items_produce_settle_hint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, policy = write_project(Path(directory))
            pending = {"items": [{"kind": "stale-knowledge", "path": "knowledge.worker"}]}
            hints = _finish_hints(manifest, policy, pending)
            self.assertTrue(any("govern settle" in hint for hint in hints), hints)

    def test_unreviewed_rooms_produce_census_hint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, policy = write_project(Path(directory))
            # No census records at all: every room reports freshness "never".
            hints = _finish_hints(manifest, policy, {"items": []})
            self.assertTrue(any("govern census --record" in hint for hint in hints), hints)

    def test_clean_project_produces_no_hints(self) -> None:
        from ag2c.model import Coverage, Policy

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "state").mkdir()
            manifest = _bare_manifest(root)
            # No targets -> no households -> nothing stale; empty pending.
            policy = Policy(
                path=root / "policy.json",
                cards=(),
                relations=(),
                contracts=(),
                checkers=(),
                coverage=Coverage(level="none", strategy="conservative", managed_by="project", areas=()),
                household_required=False,
            )
            hints = _finish_hints(manifest, policy, {"items": []})
            self.assertEqual([], hints)


class VerificationEvidenceTests(unittest.TestCase):
    """_verification_evidence_valid tolerates payload keys it does not know."""

    def _fixture(self, root: Path, *, extra: dict | None = None):
        from ag2c.ledger import append_event
        from ag2c.tasks import _verification_evidence_valid

        manifest = _bare_manifest(root)
        task = {"id": "t-x"}
        check = append_event(
            manifest.ledger_path,
            "check-run",
            {
                "task_id": "t-x",
                "results": [{"id": "c1", "stage": "floor", "status": "passed", "exit_code": 0}],
                "slice_digest": "s",
            },
        )
        payload = {
            "attempt": 1,
            "occurred_at": "2026-09-09T00:00:00+00:00",
            "passed": True,
            "changed_paths": ["app:src/x.py"],
            "change_digest": "d",
            "slice_digest": "s",
            "route_state": "conservative",
            "route": {"state": "conservative"},
            "route_cards": [],
            "checker_results": [{"id": "c1", "stage": "floor", "status": "passed", "exit_code": 0}],
            "acceptance": "ok",
            "check_ledger_event_digest": check["event_digest"],
        }
        event = append_event(
            manifest.ledger_path,
            "task-verification",
            {"task_id": "t-x", **payload, **(extra or {})},
        )
        verification = {**payload, "ledger_event_digest": event["event_digest"]}
        return manifest, task, verification, _verification_evidence_valid

    def test_unknown_extension_keys_tolerated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, task, verification, valid = self._fixture(
                Path(directory), extra={"future-field": {"new": True}}
            )
            self.assertTrue(valid(manifest, task, verification))

    def test_tampered_known_key_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, task, verification, valid = self._fixture(
                Path(directory), extra={"future-field": {"new": True}}
            )
            verification["change_digest"] = "tampered"
            self.assertFalse(valid(manifest, task, verification))

    def test_regulator_verdict_is_bound(self) -> None:
        # agent-review 落地后 regulator 是已知键：payload 与任务记录必须一致
        with tempfile.TemporaryDirectory() as directory:
            manifest, task, verification, valid = self._fixture(
                Path(directory), extra={"regulator": {"outcome": "passed"}}
            )
            verification["regulator"] = {"outcome": "passed"}
            self.assertTrue(valid(manifest, task, verification))
            verification["regulator"] = {"outcome": "rejected"}
            self.assertFalse(valid(manifest, task, verification))

    def test_missing_known_key_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, task, verification, valid = self._fixture(Path(directory))
            verification["changed_paths"] = ["app:src/other.py"]
            self.assertFalse(valid(manifest, task, verification))


if __name__ == "__main__":
    unittest.main()
