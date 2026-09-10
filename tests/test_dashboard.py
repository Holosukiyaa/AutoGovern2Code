"""Dashboard home-screen assembly tests (pure functions, no imgui)."""

from __future__ import annotations

import unittest

from ag2c_gui.dashboard import (
    DANGER,
    DECISION,
    MUTED,
    NOTICE,
    OK_DIM,
    dashboard_model,
    open_tasks,
    pending_items,
    severity_color,
    stale_knowledge,
    zone_header_color,
)


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
        self.assertEqual([0, 0, 0, 0, 0, "—", "—"], [h["value"] for h in model["health"]])
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
        self.assertIn("待结算：Knowledge 已过期 → 同步 Knowledge", model["anomalies"][0]["text"])
        health = {h["label"]: h["value"] for h in model["health"]}
        self.assertEqual(2, health["待结算"])

    def test_stale_cards_become_warnings_and_health_count(self):
        details = {"knowledge": [{"id": "k1", "status": "stale"}, {"id": "k2", "status": "current"}, {"id": "k3", "status": "unknown"}]}
        model = dashboard_model(details, {})
        self.assertEqual(
            ["知识卡过期：k1 → 复核后用 ag2c govern apply 更新该卡"],
            [a["text"] for a in model["anomalies"]],
        )
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
        """合并视图 anomalies 不再截断区①：决策项全列出（截断只发生在区②）。"""
        details = {"knowledge": [{"id": f"k{i}", "status": "stale"} for i in range(20)]}
        model = dashboard_model(details, {})
        self.assertEqual(20, model["anomaly_count"])
        self.assertEqual(20, len(model["anomalies"]))

    def test_health_counts_open_tasks(self):
        details = {"worktrees": [_task("t1"), _task("t2", state="completed")]}
        model = dashboard_model(details, {})
        health = {h["label"]: h["value"] for h in model["health"]}
        self.assertEqual(1, health["进行中任务"])

    def test_health_counts_stale_census(self):
        details = {
            "census": {
                "households": [
                    {"id": "h1", "freshness": "current"},
                    {"id": "h2", "freshness": "stale"},
                    {"id": "h3", "freshness": "stale"},
                    {"id": "h4", "freshness": "never"},
                ]
            }
        }
        model = dashboard_model(details, {})
        health = {h["label"]: h["value"] for h in model["health"]}
        self.assertEqual(2, health["普查陈旧"])

    def test_health_stale_census_tolerates_missing_census(self):
        model = dashboard_model({}, {})
        health = {h["label"]: h["value"] for h in model["health"]}
        self.assertEqual(0, health["普查陈旧"])

    def test_health_shows_baseline_debt(self):
        details = {"baseline_debt": {"total": 3, "target": 3, "over": False}}
        model = dashboard_model(details, {})
        health = {h["label"]: h["value"] for h in model["health"]}
        self.assertEqual(3, health["基线债务"])
        self.assertEqual([], model["anomalies"])

    def test_over_target_baseline_debt_is_an_error(self):
        details = {"baseline_debt": {"total": 5, "target": 3, "over": True}}
        model = dashboard_model(details, {})
        self.assertEqual(1, len(model["anomalies"]))
        self.assertEqual("error", model["anomalies"][0]["severity"])
        self.assertIn("基线债务超目标", model["anomalies"][0]["text"])
        self.assertIn("5", model["anomalies"][0]["text"])
        self.assertIn("3", model["anomalies"][0]["text"])
        self.assertEqual(1, model["anomaly_count"])

    def test_baseline_debt_tolerates_garbage(self):
        model = dashboard_model({"baseline_debt": "x"}, {})
        health = {h["label"]: h["value"] for h in model["health"]}
        self.assertEqual(0, health["基线债务"])
        self.assertEqual([], model["anomalies"])

    def test_audit_pending_is_warn_anomaly(self):
        details = {"audit": {"pending": [{"kind": "room-card", "id": "knowledge.x", "question": "q"}], "due": False, "days_since": 1}}
        model = dashboard_model(details, {})
        self.assertEqual(1, len(model["anomalies"]))
        self.assertEqual("warn", model["anomalies"][0]["severity"])
        self.assertIn("抽查待办", model["anomalies"][0]["text"])
        self.assertIn("knowledge.x", model["anomalies"][0]["text"])
        self.assertEqual(1, len(model["audit"]["pending"]))

    def test_audit_due_is_error_anomaly(self):
        details = {"audit": {"pending": [{"kind": "receipt", "id": "t001", "question": "q"}], "due": True, "days_since": 9}}
        model = dashboard_model(details, {})
        self.assertEqual("error", model["anomalies"][0]["severity"])
        self.assertIn("抽查到期", model["anomalies"][0]["text"])

    def test_health_shows_days_since_audit(self):
        model = dashboard_model({"audit": {"pending": [], "due": False, "days_since": 4}}, {})
        health = {h["label"]: h["value"] for h in model["health"]}
        self.assertEqual(4, health["距上次抽查"])

    def test_audit_tolerates_garbage(self):
        model = dashboard_model({"audit": "x"}, {})
        health = {h["label"]: h["value"] for h in model["health"]}
        self.assertEqual("—", health["距上次抽查"])
        self.assertEqual([], model["anomalies"])
        self.assertEqual([], model["audit"]["pending"])


class HelperTests(unittest.TestCase):
    def test_pending_and_stale_helpers_tolerate_garbage(self):
        self.assertEqual([], pending_items({"pending": "x"}))
        self.assertEqual([], pending_items({}))
        self.assertEqual([], stale_knowledge({"knowledge": [None, {"status": "current"}]}))


class DashboardZoneTests(unittest.TestCase):
    """三区结构：需要你处理（决策项）/ 系统警情（只需知情）/ 记录。"""

    def test_decision_items_land_in_actions_matching_attention_count(self):
        details = {
            "worktrees": [_task("t1", lifecycle="diverged", diverged=True)],
            "pending": {"items": [{"title": "Knowledge 已过期", "hint": "同步 Knowledge"}]},
            "knowledge": [{"id": "k1", "status": "stale"}],
            "audit": {"pending": [{"kind": "room-card", "id": "knowledge.x", "question": "q"}], "due": False},
        }
        model = dashboard_model(details, {})
        self.assertEqual(4, len(model["actions"]))
        self.assertEqual(4, model["attention"]["count"])
        self.assertEqual([], model["alerts"])

    def test_system_anomalies_land_in_alerts_not_actions(self):
        details = {
            "census": {"error": "boom"},
            "index": {"errors": ["e1"]},
            "baseline_debt": {"total": 5, "target": 3, "over": True},
        }
        model = dashboard_model(details, {"canonicalDirty": True, "openTasks": 0})
        self.assertEqual([], model["actions"])
        self.assertEqual(4, len(model["alerts"]))
        self.assertTrue(all(a["severity"] == "error" for a in model["alerts"]))

    def test_every_action_carries_an_action_hint(self):
        details = {
            "worktrees": [_task("t1", lifecycle="diverged", diverged=True)],
            "pending": {"items": [{"kind": "orphan"}]},
            "knowledge": [{"id": "k1", "status": "stale"}],
            "audit": {"pending": [{"kind": "receipt", "id": "t001", "question": "q"}], "due": False},
        }
        model = dashboard_model(details, {})
        self.assertEqual(4, len(model["actions"]))
        for item in model["actions"]:
            self.assertTrue("→" in item["text"] or "「已抽查」" in item["text"], item["text"])

    def test_pending_without_hint_gets_fallback_hint(self):
        model = dashboard_model({"pending": {"items": [{"kind": "orphan"}]}}, {})
        self.assertIn("govern settle", model["actions"][0]["text"])

    def test_anomalies_key_is_actions_plus_alerts(self):
        details = {
            "knowledge": [{"id": "k1", "status": "stale"}],
            "census": {"error": "boom"},
        }
        model = dashboard_model(details, {})
        self.assertEqual(model["actions"] + model["alerts"], model["anomalies"])
        self.assertEqual(2, model["anomaly_count"])

    def test_actions_are_listed_in_full_matching_attention_gate(self):
        """区①逐条列出、不截断：20 条决策项全列出，且与闸门数字一一对应。"""
        details = {"knowledge": [{"id": f"k{i}", "status": "stale"} for i in range(20)]}
        model = dashboard_model(details, {})
        self.assertEqual(20, len(model["actions"]))
        self.assertEqual(20, model["attention"]["count"])
        self.assertEqual(20, model["anomaly_count"])

    def test_attention_count_matches_actions_even_with_alerts_present(self):
        details = {
            "knowledge": [{"id": "k1", "status": "stale"}],
            "census": {"error": "boom"},
        }
        model = dashboard_model(details, {})
        self.assertEqual(1, len(model["actions"]))
        self.assertEqual(1, len(model["alerts"]))
        self.assertEqual(model["attention"]["count"], len(model["actions"]))

    def test_alerts_overflow_is_capped_with_summary(self):
        details = {"index": {"errors": [f"e{i}" for i in range(20)]}}
        model = dashboard_model(details, {})
        self.assertEqual(13, len(model["alerts"]))
        self.assertIn("另有 8 条未列出", model["alerts"][-1]["text"])
        self.assertEqual(20, model["anomaly_count"])

    def test_records_key_groups_record_sections(self):
        details = {
            "worktrees": [_task("t1")],
            "patrol": {"drills": {}, "interceptions": {"window_days": 30, "in_window": 2}},
        }
        model = dashboard_model(details, {})
        records = model["records"]
        self.assertEqual(["health", "tasks", "patrol", "hazards", "token"], list(records.keys()))
        self.assertEqual(1, len(records["tasks"]))
        self.assertTrue(records["patrol"])
        self.assertEqual(model["health"], records["health"])

    def test_records_empty_when_no_record_content(self):
        model = dashboard_model(None, None)
        records = model["records"]
        self.assertEqual([], records["tasks"])
        self.assertEqual([], records["patrol"])
        self.assertEqual([], records["hazards"])
        self.assertEqual([], records["token"])

    def test_empty_input_yields_empty_zones(self):
        model = dashboard_model(None, None)
        self.assertEqual([], model["actions"])
        self.assertEqual([], model["alerts"])
        self.assertEqual(0, model["attention"]["count"])


class PaletteTests(unittest.TestCase):
    """调色板：颜色是注意力语言——红只给高危，记录区默认灰。"""

    def test_red_is_reserved_for_error_in_every_zone(self):
        for zone in ("action", "alert", "record"):
            self.assertEqual(DANGER, severity_color(zone, "error"))
            for severity in ("warn", "ok", "info"):
                self.assertNotEqual(DANGER, severity_color(zone, severity))

    def test_decision_amber_only_marks_actionable_warns(self):
        self.assertEqual(DECISION, severity_color("action", "warn"))
        self.assertEqual(NOTICE, severity_color("alert", "warn"))
        self.assertEqual(NOTICE, severity_color("record", "warn"))

    def test_record_zone_is_muted_by_default(self):
        self.assertEqual(MUTED, severity_color("record", "info"))
        self.assertEqual(MUTED, severity_color("record", "anything-unknown"))
        self.assertEqual(OK_DIM, severity_color("record", "ok"))

    def test_unknown_combinations_degrade_to_muted(self):
        self.assertEqual(MUTED, severity_color("nowhere", "error"))
        self.assertEqual(MUTED, zone_header_color("nowhere"))

    def test_attention_ladder_dims_monotonically(self):
        """跳出度阶梯：决策琥珀 > 暗琥珀 > 暗绿 > 灰（按感知亮度）。"""

        def lum(color):
            return 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]

        self.assertGreater(lum(DECISION), lum(NOTICE))
        self.assertGreater(lum(NOTICE), lum(OK_DIM))
        self.assertGreater(lum(OK_DIM), lum(MUTED))

    def test_zone_headers_prefigure_content_level(self):
        self.assertEqual(DECISION, zone_header_color("action"))
        self.assertEqual(NOTICE, zone_header_color("alert"))
        self.assertEqual(MUTED, zone_header_color("record"))


if __name__ == "__main__":
    unittest.main()
