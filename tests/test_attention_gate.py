"""注意力总闸门：首页第一行"今天需要你决策的事：N 件"，其余排队不许插队。 只数需要人拍板的事（待结算/抽查待办/任务分叉/过期卡片）；系统错误与 演习警情是排队项，不进这个数。固定模板——制度在说话，不是 AI 在说话。"""
from __future__ import annotations

import unittest

from ag2c_gui.dashboard import dashboard_model


def _details(*, pending=0, audit=0, diverged=0, stale=0):
    return {
        "project": {"name": "demo"},
        "pending": {"items": [{"kind": "knowledge", "title": f"事项{i}"} for i in range(pending)]},
        "audit": {"pending": [{"id": f"a{i}"} for i in range(audit)]},
        "worktrees": [
            {
                "id": f"t{i}",
                "goal": "任务",
                "state": "active",
                "worktree": {"lifecycle": "diverged" if i < diverged else "constructing", "diverged": i < diverged},
            }
            for i in range(max(diverged, 1))
        ] if diverged else [],
        "knowledge": [{"id": f"k{i}", "status": "stale"} for i in range(stale)],
    }


class AttentionGateTests(unittest.TestCase):
    def test_zero_decisions_shows_quiet_line(self):
        model = dashboard_model(_details(), {})
        self.assertEqual(model["attention"]["count"], 0)
        self.assertEqual(model["attention"]["text"], "今天没有需要你决策的事")

    def test_counts_all_four_decision_kinds(self):
        model = dashboard_model(_details(pending=2, audit=1, diverged=1, stale=3), {})
        attention = model["attention"]
        self.assertEqual(attention["count"], 7)
        self.assertIn("今天需要你决策的事：7 件", attention["text"])
        self.assertIn("待结算 2", attention["text"])
        self.assertIn("抽查待办 1", attention["text"])
        self.assertIn("任务分叉 1", attention["text"])
        self.assertIn("过期卡片 3", attention["text"])

    def test_breakdown_omits_zero_kinds(self):
        model = dashboard_model(_details(pending=1), {})
        text = model["attention"]["text"]
        self.assertIn("待结算 1", text)
        self.assertNotIn("抽查待办", text)
        self.assertNotIn("任务分叉", text)
        self.assertNotIn("过期卡片", text)

    def test_non_diverged_tasks_do_not_count(self):
        details = _details()
        details["worktrees"] = [
            {"id": "t1", "goal": "施工中", "state": "active", "worktree": {"lifecycle": "constructing", "diverged": False}}
        ]
        model = dashboard_model(details, {})
        self.assertEqual(model["attention"]["count"], 0)

    def test_malformed_details_degrade_to_quiet_line(self):
        for bad in (None, {}, {"pending": "junk", "audit": [], "worktrees": "x", "knowledge": 1}):
            model = dashboard_model(bad, {})
            self.assertEqual(model["attention"]["count"], 0)
            self.assertEqual(model["attention"]["text"], "今天没有需要你决策的事")


if __name__ == "__main__":
    unittest.main()
