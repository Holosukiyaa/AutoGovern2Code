"""巡逻报告与市长看板巡逻区的测试：分类、超期判定、空账本降级。"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import bootstrap  # noqa: F401

from ag2c.ledger import append_event
from ag2c.patrol import DRILL_INTERVAL_DAYS, patrol_report

from support import bare_manifest

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


def _at(days_ago: int) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


class PatrolReportTests(unittest.TestCase):
    def _manifest_with_events(self, root: Path, events: list[tuple[str, dict, int]]):
        manifest = bare_manifest(root)
        for event_type, payload, days_ago in events:
            append_event(manifest.ledger_path, event_type, payload)
        # append_event 用真实当前时间；测试时间语义由 days_since 的单调性覆盖，
        # 精确天数在 dashboard 层用构造好的 details 测。
        return manifest

    def test_empty_ledger_degrades_gracefully(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = bare_manifest(Path(tmp))
            report = patrol_report(manifest, now=NOW)
            self.assertEqual(0, report["drills"]["gate"]["runs"])
            self.assertTrue(report["drills"]["gate"]["overdue"])  # 从未演习 = 超期
            self.assertTrue(report["drills"]["mutation"]["overdue"])
            self.assertEqual(0, report["interceptions"]["total"])

    def test_missing_ledger_never_raises(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = bare_manifest(Path(tmp) / "nonexistent")
            report = patrol_report(manifest, now=NOW)
            self.assertEqual("ag2c.patrol.v1", report["schema"])

    def test_drills_classified_by_mode(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = self._manifest_with_events(
                Path(tmp),
                [
                    ("canary", {"mode": "gate", "canary": "passed"}, 2),
                    ("canary", {"mode": "mutation", "canary": "failed", "mutation": "比较符 >→>=（graph.py:248）"}, 1),
                    ("violation-blocked", {"kind": "canonical-commit"}, 0),
                ],
            )
            report = patrol_report(manifest, now=NOW)
            self.assertEqual(1, report["drills"]["gate"]["runs"])
            self.assertEqual("passed", report["drills"]["gate"]["last_result"])
            self.assertEqual("安检演习", report["drills"]["gate"]["label"])
            self.assertEqual("failed", report["drills"]["mutation"]["last_result"])
            self.assertEqual("消防演习", report["drills"]["mutation"]["label"])
            self.assertIn("graph.py", report["drills"]["mutation"]["last_detail"])
            self.assertEqual(1, report["interceptions"]["total"])
            self.assertEqual(1, report["interceptions"]["in_window"])

    def test_recent_drill_not_overdue(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = self._manifest_with_events(
                Path(tmp), [("canary", {"mode": "gate", "canary": "passed"}, 0)]
            )
            report = patrol_report(manifest, now=NOW)
            self.assertFalse(report["drills"]["gate"]["overdue"])
            self.assertEqual(0, report["drills"]["gate"]["days_since"])


class DashboardPatrolTests(unittest.TestCase):
    def _details(self, patrol: dict) -> dict:
        return {"project": {"name": "p"}, "patrol": patrol}

    def test_failed_drill_becomes_error_anomaly_with_advice(self) -> None:
        from ag2c_gui.dashboard import dashboard_model

        details = self._details(
            {
                "drill_interval_days": DRILL_INTERVAL_DAYS,
                "drills": {
                    "gate": {"runs": 3, "label": "安检演习", "last_result": "passed", "days_since": 1, "overdue": False},
                    "mutation": {
                        "runs": 1,
                        "label": "消防演习",
                        "last_result": "failed",
                        "last_detail": "比较符 >→>=（graph.py:248）",
                        "days_since": 0,
                        "overdue": False,
                    },
                },
                "interceptions": {"total": 2, "in_window": 2, "window_days": 30, "recent": []},
            }
        )
        model = dashboard_model(details, {})
        errors = [a for a in model["anomalies"] if a["severity"] == "error"]
        self.assertEqual(1, len(errors))
        self.assertIn("消防演习报警", errors[0]["text"])
        self.assertIn("graph.py", errors[0]["text"])
        self.assertIn("补测试", errors[0]["text"])
        patrol_texts = [line["text"] for line in model["patrol"]]
        self.assertTrue(any("未被拦住" in text for text in patrol_texts))
        self.assertTrue(any("拦截 2 次" in text for text in patrol_texts))
        health = {item["label"]: item["value"] for item in model["health"]}
        self.assertEqual(0, health["距上次演习"])

    def test_never_drilled_warns_with_command_hint(self) -> None:
        from ag2c_gui.dashboard import dashboard_model

        model = dashboard_model(self._details({"drills": {}, "interceptions": {}}), {})
        warnings = [a["text"] for a in model["anomalies"] if a["severity"] == "warn"]
        self.assertTrue(any("安检演习从未举行" in text and "ag2c canary" in text for text in warnings))
        self.assertTrue(any("消防演习从未举行" in text and "--mode mutation" in text for text in warnings))
        health = {item["label"]: item["value"] for item in model["health"]}
        self.assertEqual("—", health["距上次演习"])

    def test_overdue_drill_warns(self) -> None:
        from ag2c_gui.dashboard import dashboard_model

        details = self._details(
            {
                "drill_interval_days": 7,
                "drills": {
                    "gate": {"runs": 1, "label": "安检演习", "last_result": "passed", "days_since": 10, "overdue": True},
                    "mutation": {"runs": 1, "label": "消防演习", "last_result": "passed", "days_since": 2, "overdue": False},
                },
                "interceptions": {"total": 0, "in_window": 0, "window_days": 30, "recent": []},
            }
        )
        model = dashboard_model(details, {})
        warnings = [a["text"] for a in model["anomalies"] if a["severity"] == "warn"]
        self.assertTrue(any("安检演习超期" in text and "10 天" in text for text in warnings))
        self.assertFalse(any("消防演习超期" in text for text in warnings))

    def test_missing_patrol_section_degrades(self) -> None:
        from ag2c_gui.dashboard import dashboard_model

        # patrol 段缺席 = 未知（overlay 未运行/失败），静默降级，不报"从未演习"
        model = dashboard_model({}, None)
        self.assertEqual([], model["patrol"])
        self.assertFalse(any("演习" in a["text"] for a in model["anomalies"]))


if __name__ == "__main__":
    unittest.main()
