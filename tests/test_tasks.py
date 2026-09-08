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


if __name__ == "__main__":
    unittest.main()
