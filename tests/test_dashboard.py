"""Dashboard home-screen assembly tests (pure functions, no imgui)."""

from __future__ import annotations

import threading
import time
import unittest

from clipboard_guard import (
    CLIPBOARD_LOCKED_MARK,
    ClipboardLock,
    require_clipboard,
)
from ag2c_gui.custody import custody_model
from ag2c_gui.dashboard import (
    DANGER,
    DECISION,
    HERO_FONT_SCALE,
    MUTED,
    NOTICE,
    OK_DIM,
    dashboard_model,
    hero_block,
    open_tasks,
    pending_items,
    section_prompt,
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


class HeroBlockTests(unittest.TestCase):
    """视觉主体：注意力闸门即页面主体。"""

    def test_hero_mirrors_attention_gate(self):
        model = dashboard_model({"knowledge": [{"id": "k1", "status": "stale"}]}, {})
        hero = hero_block(model)
        self.assertEqual(1, hero["count"])
        self.assertIn("1 件", hero["text"])
        self.assertTrue(hero["has_actions"])

    def test_hero_all_clear(self):
        hero = hero_block(dashboard_model({}, {}))
        self.assertEqual(0, hero["count"])
        self.assertIn("没有", hero["text"])
        self.assertFalse(hero["has_actions"])

    def test_hero_tolerates_garbage(self):
        self.assertEqual({"text": "", "count": 0, "has_actions": False}, hero_block(None))
        self.assertEqual({"text": "", "count": 0, "has_actions": False}, hero_block({"attention": "x", "actions": "y"}))

    def test_hero_font_scale_is_significantly_larger(self):
        self.assertGreaterEqual(HERO_FONT_SCALE, 1.5)


class CustodyModelTests(unittest.TestCase):
    def test_empty_desk_and_human_veto(self) -> None:
        empty = custody_model(None)
        self.assertTrue(empty["empty"]); self.assertEqual("先选择一个项目", empty["headline"])
        quiet = custody_model({"project": {"name": "p"}, "proxy": {"auto_settle": True}})
        self.assertEqual("刚才没有要你点的", quiet["headline"]); self.assertFalse(quiet["veto"])
        granted = custody_model({"project": {"name": "p"}, "proxy": {"auto_settle": True, "auto_census": True, "recent": [{"rule": "settle"}]}, "pending": {"items": [{"kind": "stale-knowledge", "title": "过期卡", "path": "k1"}, {"kind": "census-review-required", "title": "普查", "path": "room"}]}, "worktrees": [{"id": "t1", "state": "open", "worktree": {"lifecycle": "verified-unmerged"}}, {"id": "t2", "state": "open", "worktree": {"diverged": True}}]})
        self.assertEqual(["settle"], [w["rule"] for w in granted["watch"]])
        self.assertEqual(["merge", "diverged"], [v["kind"] for v in granted["veto"]]); self.assertIn("永不代理", granted["irreversible"])
        held = custody_model({"project": {"name": "p"}, "proxy": {}, "pending": {"items": [{"kind": "stale-knowledge", "title": "过期卡", "path": "k1"}]}})
        self.assertEqual(["stale-knowledge"], [v["kind"] for v in held["veto"]])


class SectionPromptTests(unittest.TestCase):
    """复制按钮的提示词：固定模板 + 项目名 + 逐条文本（制度在说话）。"""

    def test_actions_prompt_numbers_every_item_with_project(self):
        items = [
            {"severity": "warn", "text": "待结算：Knowledge 已过期 → 运行 ag2c govern settle 结算"},
            {"severity": "error", "text": "任务 t1 的 worktree 已分叉 → ag2c task refresh 同步"},
        ]
        prompt = section_prompt("actions", "demo", items)
        self.assertIn("demo", prompt)
        self.assertIn("需要你处理", prompt)
        self.assertIn("1. 待结算：Knowledge 已过期", prompt)
        self.assertIn("2. 任务 t1 的 worktree 已分叉", prompt)

    def test_empty_items_yield_empty_state_prompt(self):
        prompt = section_prompt("alerts", "demo", [])
        self.assertIn("系统警情", prompt)
        self.assertIn("没有条目", prompt)

    def test_task_items_fall_back_to_goal_then_id(self):
        items = [{"id": "t1", "goal": "修看板"}, {"id": "t2"}, {"goal": "   "}]
        prompt = section_prompt("tasks", "", items)
        self.assertIn("1. 修看板", prompt)
        self.assertIn("2. t2", prompt)
        self.assertNotIn("3.", prompt)

    def test_garbage_items_are_skipped_without_raising(self):
        prompt = section_prompt("patrol", "demo", [None, "x", {"text": ""}, {"text": "演习已通过"}])
        self.assertIn("1. 演习已通过", prompt)
        self.assertNotIn("2.", prompt)

    def test_unknown_kind_degrades_to_generic_template(self):
        prompt = section_prompt("nope", "demo", [{"text": "x"}])
        self.assertIn("记录", prompt)
        self.assertIn("1. x", prompt)

    def test_missing_project_name_is_omitted(self):
        prompt = section_prompt("token", None, [{"text": "本月 $1.00"}])
        self.assertNotIn("「", prompt)
        self.assertIn("治理成本", prompt)


class WebViewPageTests(unittest.TestCase):
    """Home page is HTML/CSS in the WebView host, not an imgui frame loop."""

    def test_static_page_has_three_zones_and_ops_strip(self):
        from ag2c_gui.webview_host import UI_INDEX_HTML

        self.assertIn('id="ops"', UI_INDEX_HTML)
        self.assertIn("要你处理", UI_INDEX_HTML)
        self.assertIn("系统警情", UI_INDEX_HTML)
        self.assertIn("记录", UI_INDEX_HTML)
        self.assertIn("操作日志", UI_INDEX_HTML)
        self.assertIn("施工", UI_INDEX_HTML)
        self.assertIn("实际记录", UI_INDEX_HTML)
        self.assertIn("AI 入口", UI_INDEX_HTML)
        self.assertIn('id="project"', UI_INDEX_HTML)
        self.assertIn('id="refresh"', UI_INDEX_HTML)
        self.assertIn("没有要你处理的事", UI_INDEX_HTML)
        self.assertNotIn("imgui_bundle", UI_INDEX_HTML)

    def test_ops_render_audit_lines_not_json_dump(self):
        from ag2c_gui.webview_ui import UI_APP_JS, UI_LAYOUT_CSS

        self.assertIn("payload.lines", UI_APP_JS)
        self.assertIn('function renderOps', UI_APP_JS)
        self.assertNotIn("JSON.stringify(payload.worktrees", UI_APP_JS)
        self.assertNotIn("JSON.stringify(payload.journal", UI_APP_JS)
        self.assertIn("tree home inspect", UI_LAYOUT_CSS)
        self.assertIn('"ops ops ops"', UI_LAYOUT_CSS)

    def test_clipboard_guard_skips_when_locked(self):
        with ClipboardLock() as lock:
            if not lock.held:
                raise unittest.SkipTest(
                    f"{CLIPBOARD_LOCKED_MARK}: could not acquire fixture lock"
                )
            with self.assertRaises(unittest.SkipTest) as raised:
                require_clipboard(retries=2, wait_s=0.0)
            self.assertIn(CLIPBOARD_LOCKED_MARK, str(raised.exception))

    def test_clipboard_guard_retries_then_proceeds(self):
        lock = ClipboardLock()
        lock.__enter__()
        self.addCleanup(lock.release)
        if not lock.held:
            raise unittest.SkipTest(
                f"{CLIPBOARD_LOCKED_MARK}: could not acquire fixture lock"
            )

        def _unlock_soon() -> None:
            time.sleep(0.12)
            lock.release()

        threading.Thread(target=_unlock_soon, daemon=True).start()
        require_clipboard(retries=8, wait_s=0.05)

    def test_importing_dashboard_leaves_no_ini_debris(self):
        import os
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            previous = os.getcwd()
            try:
                os.chdir(directory)
                dashboard_model(None, None)
                from ag2c_gui.webview_host import UI_INDEX_HTML

                self.assertIn('id="home"', UI_INDEX_HTML)
            finally:
                os.chdir(previous)
            debris = sorted(p.name for p in Path(directory).glob("*.ini"))
            self.assertEqual(debris, [], f"装配首页在 cwd 落了 ini 碎屑: {debris}")
