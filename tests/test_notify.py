"""Notification queue: file-based JSONL, per-project isolation, ring buffer."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from ag2c.notify import (
    KIND_CANONICAL_DIRTY,
    KIND_CENSUS_STALE,
    KIND_GATE_BLOCK,
    KIND_HAZARD,
    acknowledge,
    acknowledge_all,
    notification_count,
    notify,
    pending_notifications,
    prune_notification_conditions,
    sync_notification,
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


class SyncNotificationTests(unittest.TestCase):
    """条件同步去重原语：首现通知 / 重复去重 / 升级再报 / 指纹变化再报 / 消失清除后再现重报。"""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._old = os.environ.get("AG2C_DATA_ROOT", "")
        os.environ["AG2C_DATA_ROOT"] = self._tmp

    def tearDown(self) -> None:
        if self._old:
            os.environ["AG2C_DATA_ROOT"] = self._old
        else:
            os.environ.pop("AG2C_DATA_ROOT", None)

    def test_first_appearance_notifies_then_dedups(self) -> None:
        sent = sync_notification("proj1", "cond", active=True, kind=KIND_HAZARD, title="警情", level=60)
        self.assertIsNotNone(sent)
        self.assertEqual(sent["kind"], KIND_HAZARD)
        again = sync_notification("proj1", "cond", active=True, kind=KIND_HAZARD, title="警情", level=60)
        self.assertIsNone(again)
        self.assertEqual(notification_count("proj1"), 1)

    def test_level_upgrade_renotifies(self) -> None:
        sync_notification("proj1", "cond", active=True, kind=KIND_HAZARD, title="警情", level=50)
        sent = sync_notification("proj1", "cond", active=True, kind=KIND_HAZARD, title="警情", level=55)
        self.assertIsNotNone(sent)
        # 同级与降级都不再报
        self.assertIsNone(sync_notification("proj1", "cond", active=True, kind=KIND_HAZARD, title="警情", level=55))
        self.assertIsNone(sync_notification("proj1", "cond", active=True, kind=KIND_HAZARD, title="警情", level=50))
        self.assertEqual(notification_count("proj1"), 2)

    def test_fingerprint_change_renotifies(self) -> None:
        sync_notification("proj1", "cond", active=True, kind=KIND_CANONICAL_DIRTY, title="脏", fingerprint="aaa")
        sent = sync_notification("proj1", "cond", active=True, kind=KIND_CANONICAL_DIRTY, title="脏", fingerprint="bbb")
        self.assertIsNotNone(sent)
        self.assertEqual(notification_count("proj1"), 2)

    def test_inactive_clears_and_reappearance_renotifies(self) -> None:
        sync_notification("proj1", "cond", active=True, kind=KIND_HAZARD, title="警情", level=60)
        self.assertIsNone(sync_notification("proj1", "cond", active=False))
        self.assertEqual(notification_count("proj1"), 1)  # 清除不发通知
        sent = sync_notification("proj1", "cond", active=True, kind=KIND_HAZARD, title="警情", level=60)
        self.assertIsNotNone(sent)  # 清除后再现 = 首现，同级也重报
        self.assertEqual(notification_count("proj1"), 2)

    def test_empty_key_and_inactive_unknown_key_are_noop(self) -> None:
        self.assertIsNone(sync_notification("proj1", "", active=True, kind=KIND_HAZARD, title="x"))
        self.assertIsNone(sync_notification("proj1", "never-seen", active=False))
        self.assertEqual(notification_count("proj1"), 0)

    def test_prune_removes_only_unkept_prefixed_keys(self) -> None:
        sync_notification("proj1", "hazard:a", active=True, kind=KIND_HAZARD, title="a", level=60)
        sync_notification("proj1", "hazard:b", active=True, kind=KIND_HAZARD, title="b", level=50)
        sync_notification("proj1", "other:c", active=True, kind=KIND_CENSUS_STALE, title="c")
        removed = prune_notification_conditions("proj1", "hazard:", {"hazard:b"})
        self.assertEqual(["hazard:a"], removed)
        # hazard:b 保留（仍去重），other:c 不在前缀内不受影响
        self.assertIsNone(sync_notification("proj1", "hazard:b", active=True, kind=KIND_HAZARD, title="b", level=50))
        self.assertIsNone(sync_notification("proj1", "other:c", active=True, kind=KIND_CENSUS_STALE, title="c"))
        # 被清的 hazard:a 重现即重报
        self.assertIsNotNone(sync_notification("proj1", "hazard:a", active=True, kind=KIND_HAZARD, title="a", level=60))


class CensusStaleNotificationTests(unittest.TestCase):
    """census-stale 空炮接线：新鲜度问题集路由到 KIND_CENSUS_STALE，去重+变化再报+通过清除。"""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._old = os.environ.get("AG2C_DATA_ROOT", "")
        os.environ["AG2C_DATA_ROOT"] = self._tmp
        from ag2c.model import Manifest

        self._manifest = Manifest(
            path=Path(self._tmp) / "manifest.json",
            project_id="test-proj",
            project_root=Path(self._tmp),
            targets=[],
            ledger_path=Path(self._tmp) / "ledger.jsonl",
            policy_path=Path(self._tmp) / "policy.json",
            state_dir=Path(self._tmp) / "state",
        )

    def tearDown(self) -> None:
        if self._old:
            os.environ["AG2C_DATA_ROOT"] = self._old
        else:
            os.environ.pop("AG2C_DATA_ROOT", None)

    def test_stale_rooms_notify_once_and_change_renotifies(self) -> None:
        from ag2c.households import _sync_census_stale_notification

        _sync_census_stale_notification(self._manifest, ["census-stale:knowledge.src"])
        items = pending_notifications("test-proj")
        self.assertEqual(1, len(items))
        self.assertEqual(KIND_CENSUS_STALE, items[0]["kind"])
        self.assertIn("knowledge.src", items[0]["detail"])
        # 同一批房间持续陈旧 → 去重
        _sync_census_stale_notification(self._manifest, ["census-stale:knowledge.src"])
        self.assertEqual(1, notification_count("test-proj"))
        # 房间集变化 → 再报
        _sync_census_stale_notification(self._manifest, ["census-stale:knowledge.src", "census-never:knowledge.gui"])
        self.assertEqual(2, notification_count("test-proj"))

    def test_clean_gate_clears_and_redowngrade_renotifies(self) -> None:
        from ag2c.households import _sync_census_stale_notification

        _sync_census_stale_notification(self._manifest, ["census-stale:knowledge.src"])
        _sync_census_stale_notification(self._manifest, [])  # 门禁通过 → 清除
        self.assertEqual(1, notification_count("test-proj"))
        _sync_census_stale_notification(self._manifest, ["census-stale:knowledge.src"])
        self.assertEqual(2, notification_count("test-proj"))  # 重新降级重新报


class CanonicalDirtyNotificationTests(unittest.TestCase):
    """canonical-dirty 空炮接线：dirty 路径集为指纹，干净清除。"""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._old = os.environ.get("AG2C_DATA_ROOT", "")
        os.environ["AG2C_DATA_ROOT"] = self._tmp
        # 无 manifest 的裸目录：_project_id_for 降级为目录名
        self._canonical = Path(self._tmp) / "proj-canonical"
        self._canonical.mkdir()

    def tearDown(self) -> None:
        if self._old:
            os.environ["AG2C_DATA_ROOT"] = self._old
        else:
            os.environ.pop("AG2C_DATA_ROOT", None)

    def test_dirty_notifies_dedups_and_path_change_renotifies(self) -> None:
        from ag2c.tasks import _sync_canonical_dirty_notification

        project_id = self._canonical.name
        _sync_canonical_dirty_notification(self._canonical, ["src/app.py"], task_id="t1")
        items = pending_notifications(project_id)
        self.assertEqual(1, len(items))
        self.assertEqual(KIND_CANONICAL_DIRTY, items[0]["kind"])
        self.assertEqual("t1", items[0]["task_id"])
        self.assertIn("src/app.py", items[0]["detail"])
        # 同一批路径持续脏 → 去重
        _sync_canonical_dirty_notification(self._canonical, ["src/app.py"], task_id="t1")
        self.assertEqual(1, notification_count(project_id))
        # 路径集变化 → 再报
        _sync_canonical_dirty_notification(self._canonical, ["src/app.py", "README.md"], task_id="t1")
        self.assertEqual(2, notification_count(project_id))

    def test_clean_clears_and_redirty_renotifies(self) -> None:
        from ag2c.tasks import _sync_canonical_dirty_notification

        project_id = self._canonical.name
        _sync_canonical_dirty_notification(self._canonical, ["src/app.py"])
        _sync_canonical_dirty_notification(self._canonical, [])  # 干净 → 清除
        _sync_canonical_dirty_notification(self._canonical, ["src/app.py"])
        self.assertEqual(2, notification_count(project_id))  # 重新变脏重新报


class HazardPushTests(unittest.TestCase):
    """危房推模式：severity≥50 首现推、升级再报、消失清除后再现重报、低档位静默。"""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._old = os.environ.get("AG2C_DATA_ROOT", "")
        os.environ["AG2C_DATA_ROOT"] = self._tmp
        from ag2c.model import Manifest

        self._manifest = Manifest(
            path=Path(self._tmp) / "manifest.json",
            project_id="test-proj",
            project_root=Path(self._tmp),
            targets=[],
            ledger_path=Path(self._tmp) / "ledger.jsonl",
            policy_path=Path(self._tmp) / "policy.json",
            state_dir=Path(self._tmp) / "state",
        )

    def tearDown(self) -> None:
        if self._old:
            os.environ["AG2C_DATA_ROOT"] = self._old
        else:
            os.environ.pop("AG2C_DATA_ROOT", None)

    @staticmethod
    def _report(*entries: dict) -> dict:
        return {"schema": "ag2c.hazard.v1", "hazards": list(entries), "counts": {}}

    @staticmethod
    def _entry(kind: str, target: str, severity: int, detail: str = "详情", suggestion: str = "建议") -> dict:
        return {"kind": kind, "target": target, "severity": severity, "detail": detail, "suggestion": suggestion}

    def test_critical_hazard_pushes_with_suggestion(self) -> None:
        from ag2c.hazard import push_critical_hazards

        pushed = push_critical_hazards(self._manifest, report=self._report(self._entry("guard-removed", "core.hooksPath", 60)))
        self.assertEqual(1, len(pushed))
        self.assertEqual(KIND_HAZARD, pushed[0]["kind"])
        self.assertIn("guard-removed", pushed[0]["title"])
        self.assertIn("建议", pushed[0]["detail"])

    def test_below_threshold_silent(self) -> None:
        from ag2c.hazard import push_critical_hazards

        pushed = push_critical_hazards(self._manifest, report=self._report(self._entry("hollow", "src/a.py", 40)))
        self.assertEqual([], pushed)
        self.assertEqual(0, notification_count("test-proj"))

    def test_dedup_and_escalation_renotifies(self) -> None:
        from ag2c.hazard import push_critical_hazards

        entry = self._entry("regulator-absent", "regulator", 50)
        push_critical_hazards(self._manifest, report=self._report(entry))
        # 同一条目同一 severity → 去重
        self.assertEqual([], push_critical_hazards(self._manifest, report=self._report(entry)))
        self.assertEqual(1, notification_count("test-proj"))
        # severity 升级（连续缺席计数长大）→ 再报
        escalated = self._entry("regulator-absent", "regulator", 51)
        self.assertEqual(1, len(push_critical_hazards(self._manifest, report=self._report(escalated))))
        self.assertEqual(2, notification_count("test-proj"))

    def test_disappearance_clears_and_reappearance_renotifies(self) -> None:
        from ag2c.hazard import push_critical_hazards

        entry = self._entry("guard-removed", "core.hooksPath", 60)
        push_critical_hazards(self._manifest, report=self._report(entry))
        # 条目消失（修复或豁免）→ 去重键清除
        self.assertEqual([], push_critical_hazards(self._manifest, report=self._report()))
        # 重现（豁免日落到期）→ 重新报
        self.assertEqual(1, len(push_critical_hazards(self._manifest, report=self._report(entry))))
        self.assertEqual(2, notification_count("test-proj"))

    def test_garbage_report_degrades_to_empty(self) -> None:
        from ag2c.hazard import push_critical_hazards

        self.assertEqual([], push_critical_hazards(self._manifest, report={"hazards": "not-a-list"}))
        self.assertEqual([], push_critical_hazards(self._manifest, report={"hazards": [None, "junk"]}))
        self.assertEqual(0, notification_count("test-proj"))


class CensusStaleGateWiringTests(unittest.TestCase):
    """门禁级接线（监管要求的兑现证据）：驱动真实 enforce_households—— 块时双通知（gate-block 事件型 + census-stale 条件型）、重复块去重、 门禁通过清除、再降级重报。夹具保真：gated=True + record_census。"""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._old = os.environ.get("AG2C_DATA_ROOT", "")
        os.environ["AG2C_DATA_ROOT"] = self._tmp

    def tearDown(self) -> None:
        if self._old:
            os.environ["AG2C_DATA_ROOT"] = self._old
        else:
            os.environ.pop("AG2C_DATA_ROOT", None)

    def test_gate_block_double_notifies_and_dedups(self) -> None:
        from support import record_census, write_project

        from ag2c.config import discover_manifest, load_manifest, load_policy
        from ag2c.errors import AG2CError
        from ag2c.households import enforce_households
        from ag2c.index import build_index
        from ag2c.slicer import compile_slice

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_project(root, gated=True)
            record_census(root)

            def _reload():
                manifest = load_manifest(discover_manifest(root))
                return manifest, load_policy(manifest)

            def _enforce():
                manifest, policy = _reload()
                build_index(manifest, policy)
                slice_ = compile_slice(manifest, policy, path_specs=["app:src/api/service.py"])
                enforce_households(manifest, policy, slice_, {item["id"] for item in slice_["check_plan"]})

            # 干净：门禁通过，无任何通知
            _enforce()
            self.assertEqual(0, notification_count("test-project"))

            # 漂移：knowledge.api 陈旧 → 门禁块，双通知各一
            (root / "src" / "api" / "service.py").write_text("VALUE = 'drifted'\n", encoding="utf-8")
            with self.assertRaises(AG2CError):
                _enforce()
            kinds = [item["kind"] for item in pending_notifications("test-project")]
            self.assertEqual(1, kinds.count(KIND_GATE_BLOCK))
            self.assertEqual(1, kinds.count(KIND_CENSUS_STALE))

            # 重复块：gate-block 是事件型再发一次；census-stale 是条件型去重
            with self.assertRaises(AG2CError):
                _enforce()
            kinds = [item["kind"] for item in pending_notifications("test-project")]
            self.assertEqual(2, kinds.count(KIND_GATE_BLOCK))
            self.assertEqual(1, kinds.count(KIND_CENSUS_STALE))

            # 重录普查 → 门禁通过 → census-stale 去重键清除（不发通知）
            record_census(root)
            _enforce()
            self.assertEqual(3, notification_count("test-project"))

            # 再降级 → census-stale 重报
            (root / "src" / "api" / "service.py").write_text("VALUE = 'drifted-again'\n", encoding="utf-8")
            with self.assertRaises(AG2CError):
                _enforce()
            kinds = [item["kind"] for item in pending_notifications("test-project")]
            self.assertEqual(3, kinds.count(KIND_GATE_BLOCK))
            self.assertEqual(2, kinds.count(KIND_CENSUS_STALE))


class HazardPushTrayIntegrationTests(unittest.TestCase):
    """任务4 监管遗留的集成兑现：真实驱动托盘轮询路径（management.project_details） → 真实危房检测（guard-removed：纳管登记在、core.hooksPath 未装）→ KIND_HAZARD 通知落队列；二次轮询去重不轰炸。与 HazardPushTests 的函数级用例互补： 那些注合成报告证 push_critical_hazards，这条证 overlay 接线本身不是空炮。"""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._old = os.environ.get("AG2C_DATA_ROOT", "")
        os.environ["AG2C_DATA_ROOT"] = self._tmp

    def tearDown(self) -> None:
        if self._old:
            os.environ["AG2C_DATA_ROOT"] = self._old
        else:
            os.environ.pop("AG2C_DATA_ROOT", None)

    def test_tray_poll_pushes_critical_hazard_and_dedups(self) -> None:
        import subprocess

        from support import git_project

        from ag2c.enrollment import enroll_project
        from ag2c.management import project_details

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            # 生产拓扑夹具（与 test_coordinates._project 同款）：真实纳管进隔离
            # 数据根——activation.json 与守卫由 enrollment 真实安装，manifest 可发现。
            os.environ["AG2C_DATA_ROOT"] = str(base / "ag2c-data")
            root = git_project(base / "proj")
            enroll_project(root, skill_root=base / "skills", harnesses=("agents",))
            # 真实 guard-removed：纳管登记在，但守卫被拆（core.hooksPath 未设置）
            subprocess.run(
                ["git", "-C", str(root), "config", "--unset", "core.hooksPath"],
                check=True,
                capture_output=True,
            )

            details = project_details(root, refresh=True)
            self.assertTrue(details["available"])
            hazard_kinds = [entry["kind"] for entry in details["hazards"]["hazards"]]
            self.assertIn("guard-removed", hazard_kinds)  # 检测本身真实命中（severity 60 ≥ 50）

            project_id = details["manifest"]["project_id"]
            pushed = [item for item in pending_notifications(project_id) if item["kind"] == KIND_HAZARD]
            self.assertEqual(1, len(pushed))
            self.assertIn("guard-removed", pushed[0]["title"])
            self.assertIn("60", pushed[0]["title"])

            # 托盘再次轮询（看板开着 = 高频轮询）：同一条目不重复轰炸
            project_details(root, refresh=True)
            project_details(root, refresh=True)
            self.assertEqual(1, notification_count(project_id))
