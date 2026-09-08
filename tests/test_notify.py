"""Notification queue: file-based JSONL, per-project isolation, ring buffer."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from ag2c.notify import (
    KIND_GATE_BLOCK,
    acknowledge,
    acknowledge_all,
    notification_count,
    notify,
    pending_notifications,
)


class NotifyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._old = os.environ.get("AG2C_DATA_ROOT", "")
        os.environ["AG2C_DATA_ROOT"] = self._tmp

    def tearDown(self) -> None:
        if self._old:
            os.environ["AG2C_DATA_ROOT"] = self._old
        else:
            os.environ.pop("AG2C_DATA_ROOT", None)

    def test_notify_and_read(self) -> None:
        notify("proj1", KIND_GATE_BLOCK, "门禁拦截", "census-stale:knowledge.src")
        items = pending_notifications("proj1")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["kind"], KIND_GATE_BLOCK)
        self.assertEqual(items[0]["title"], "门禁拦截")
        self.assertIn("census-stale", items[0]["detail"])
        self.assertFalse(items[0]["acknowledged"])

    def test_project_isolation(self) -> None:
        notify("proj1", KIND_GATE_BLOCK, "项目1的通知")
        notify("proj2", KIND_GATE_BLOCK, "项目2的通知")
        self.assertEqual(len(pending_notifications("proj1")), 1)
        self.assertEqual(len(pending_notifications("proj2")), 1)
        self.assertEqual(pending_notifications("proj1")[0]["title"], "项目1的通知")

    def test_acknowledge(self) -> None:
        item = notify("proj1", KIND_GATE_BLOCK, "测试")
        self.assertEqual(notification_count("proj1"), 1)
        self.assertTrue(acknowledge("proj1", item["id"]))
        self.assertEqual(notification_count("proj1"), 0)
        self.assertFalse(acknowledge("proj1", "nonexistent"))

    def test_acknowledge_all(self) -> None:
        notify("proj1", KIND_GATE_BLOCK, "通知1")
        notify("proj1", KIND_GATE_BLOCK, "通知2")
        notify("proj1", KIND_GATE_BLOCK, "通知3")
        self.assertEqual(acknowledge_all("proj1"), 3)
        self.assertEqual(notification_count("proj1"), 0)

    def test_ring_buffer_caps_at_max(self) -> None:
        for i in range(210):
            notify("proj1", KIND_GATE_BLOCK, f"通知{i}")
        items = pending_notifications("proj1")
        self.assertLessEqual(len(items), 200)

    def test_notify_with_task_and_room(self) -> None:
        item = notify("proj1", KIND_GATE_BLOCK, "门禁", "detail", task_id="t1", room_id="knowledge.src")
        self.assertEqual(item["task_id"], "t1")
        self.assertEqual(item["room_id"], "knowledge.src")

    def test_empty_queue_returns_empty(self) -> None:
        self.assertEqual(pending_notifications("nonexistent"), [])
        self.assertEqual(notification_count("nonexistent"), 0)

    def test_corrupt_lines_skipped(self) -> None:
        path = Path(self._tmp) / "notifications" / "proj1.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            '{"schema":"ag2c.notification.v1","id":"1","kind":"gate-block","title":"good","detail":"","task_id":"","room_id":"","created_at":"","acknowledged":false}\n'
            "not json\n"
            '{"schema":"other","id":"2"}\n',
            encoding="utf-8",
        )
        items = pending_notifications("proj1")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "good")


class GateBlockNotificationTests(unittest.TestCase):
    """Verify that gate blocks write notifications."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._old = os.environ.get("AG2C_DATA_ROOT", "")
        os.environ["AG2C_DATA_ROOT"] = self._tmp

    def tearDown(self) -> None:
        if self._old:
            os.environ["AG2C_DATA_ROOT"] = self._old
        else:
            os.environ.pop("AG2C_DATA_ROOT", None)

    def test_household_gate_notifies(self) -> None:
        """enforce_households writes a notification before raising."""
        from ag2c.households import _notify_gate
        from ag2c.model import Manifest

        manifest = Manifest(
            path=Path(self._tmp) / "manifest.json",
            project_id="test-proj",
            project_root=Path(self._tmp),
            targets=[],
            ledger_path=Path(self._tmp) / "ledger.jsonl",
            policy_path=Path(self._tmp) / "policy.json",
            state_dir=Path(self._tmp) / "state",
        )
        _notify_gate(manifest, ["census-stale:knowledge.src", "span-file-gap:knowledge.gui"])
        items = pending_notifications("test-proj")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["kind"], KIND_GATE_BLOCK)
        self.assertIn("census-stale", items[0]["detail"])


if __name__ == "__main__":
    unittest.main()
