"""Dashboard home-screen assembly tests (pure functions, no imgui)."""

from __future__ import annotations

import unittest

from ag2c_gui.dashboard import dashboard_model, open_tasks, pending_items, stale_knowledge


def _task(task_id: str, state: str = "open", **worktree):
    return {"id": task_id, "goal": f"goal of {task_id}", "state": state, "worktree": worktree}


class OpenTaskTests(unittest.TestCase):
    def test_terminal_states_are_filtered(self):
        details = {
            "worktrees": [
                _task("t1", state="open"),
                _task("t2", state="completed"),
                _task("t3", state="abandoned"),
                _task("t4", state="open", lifecycle="verified-unmerged"),
            ]
        }
        tasks = open_tasks(details)
        self.assertEqual(["t1", "t4"], [t["id"] for t in tasks])
        self.assertEqual("已验证待合并", tasks[1]["lifecycle_label"])

    def test_goal_is_clipped_to_one_line(self):
        long_goal = "很长的目标 " * 30
        tasks = open_tasks({"worktrees": [{"id": "t", "goal": long_goal, "state": "open"}]})
        self.assertLessEqual(len(tasks[0]["goal"]), 60)
        self.assertTrue(tasks[0]["goal"].endswith("…"))

    def test_garbage_rows_are_skipped(self):
        self.assertEqual([], open_tasks({"worktrees": [None, "x", 42]}))
        self.assertEqual([], open_tasks({}))


class DashboardModelTests(unittest.TestCase):
    def test_empty_input_yields_empty_sections_without_raising(self):
        model = dashboard_model(None, None)
        self.assertEqual([], model["tasks"])
        self.assertEqual([], model["anomalies"])
        self.assertEqual(0, model["anomaly_count"])
        self.assertEqual([0, 0, 0], [h["value"] for h in model["health"]])
        self.assertEqual("", model["project"])

    def test_all_green_project_is_nearly_empty(self):
        details = {
            "project": {"name": "demo"},
            "worktrees": [_task("done", state="completed")],
            "pending": {"items": []},
            "knowledge": [{"id": "k1", "status": "current"}],
            "census": {},
            "index": {"errors": []},
        }
        model = dashboard_model(details, {"canonicalDirty": False, "openTasks": 0})
        self.assertEqual("demo", model["project"])
        self.assertEqual([], model["tasks"])
        self.assertEqual([], model["anomalies"])

    def test_dirty_canonical_without_open_task_is_an_error(self):
        model = dashboard_model({}, {"canonicalDirty": True, "openTasks": 0})
        self.assertEqual(1, len(model["anomalies"]))
        self.assertEqual("error", model["anomalies"][0]["severity"])
        self.assertIn("canonical", model["anomalies"][0]["text"])

    def test_dirty_canonical_during_open_task_is_not_an_anomaly(self):
        details = {"worktrees": [_task("t1")]}
        model = dashboard_model(details, {"canonicalDirty": True, "openTasks": 1})
        self.assertEqual([], model["anomalies"])

    def test_guard_error_never_raises_the_dirty_alarm(self):
        model = dashboard_model({}, {"canonicalDirty": True, "error": True})
        self.assertEqual([], model["anomalies"])

    def test_diverged_worktree_is_an_error(self):
        details = {"worktrees": [_task("t1", lifecycle="diverged", diverged=True)]}
        model = dashboard_model(details, {})
        self.assertTrue(any("分叉" in a["text"] and a["severity"] == "error" for a in model["anomalies"]))

    def test_pending_items_become_warnings_and_health_count(self):
        details = {"pending": {"items": [{"title": "Knowledge 已过期", "hint": "同步 Knowledge"}, {"kind": "orphan"}]}}
        model = dashboard_model(details, {})
        self.assertEqual(2, len(model["anomalies"]))
        self.assertIn("待结算：Knowledge 已过期（同步 Knowledge）", model["anomalies"][0]["text"])
        health = {h["label"]: h["value"] for h in model["health"]}
        self.assertEqual(2, health["待结算"])

    def test_stale_cards_become_warnings_and_health_count(self):
        details = {"knowledge": [{"id": "k1", "status": "stale"}, {"id": "k2", "status": "current"}, {"id": "k3", "status": "unknown"}]}
        model = dashboard_model(details, {})
        self.assertEqual(["知识卡过期：k1"], [a["text"] for a in model["anomalies"]])
        health = {h["label"]: h["value"] for h in model["health"]}
        self.assertEqual(1, health["过期卡片"])

    def test_census_and_index_errors_are_errors(self):
        details = {"census": {"error": "boom"}, "index": {"errors": ["e1", "e2"]}}
        model = dashboard_model(details, {})
        texts = [a["text"] for a in model["anomalies"]]
        self.assertIn("普查失败：boom", texts)
        self.assertIn("索引错误：e1", texts)
        self.assertIn("索引错误：e2", texts)
        self.assertTrue(all(a["severity"] == "error" for a in model["anomalies"]))

    def test_anomaly_overflow_is_summarized(self):
        details = {"knowledge": [{"id": f"k{i}", "status": "stale"} for i in range(20)]}
        model = dashboard_model(details, {})
        self.assertEqual(20, model["anomaly_count"])
        self.assertEqual(13, len(model["anomalies"]))
        self.assertIn("另有 8 条未列出", model["anomalies"][-1]["text"])

    def test_health_counts_open_tasks(self):
        details = {"worktrees": [_task("t1"), _task("t2", state="completed")]}
        model = dashboard_model(details, {})
        health = {h["label"]: h["value"] for h in model["health"]}
        self.assertEqual(1, health["进行中任务"])


class HelperTests(unittest.TestCase):
    def test_pending_and_stale_helpers_tolerate_garbage(self):
        self.assertEqual([], pending_items({"pending": "x"}))
        self.assertEqual([], pending_items({}))
        self.assertEqual([], stale_knowledge({"knowledge": [None, {"status": "current"}]}))


if __name__ == "__main__":
    unittest.main()
