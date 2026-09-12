"""绿灯带阴影：每个"通过"旁标注本次未检查什么（反向引导收口规则 3）。 阴影数据全部来自任务验证记录的既有字段（acceptance / checker_results / regulator），dashboard 层纯函数装配；字段缺失或畸形时静默降级，绝不编造。"""
from __future__ import annotations

import unittest

from ag2c_gui.dashboard import dashboard_model, open_tasks, verification_shadow


def _verification(**overrides):
    base = {
        "acceptance": {
            "static": "passed",
            "floor": "passed",
            "boundary": "not-run",
            "scenario": "not-applicable",
            "complete": "not-run",
        },
        "checker_results": [
            {"id": "check.python", "stage": "floor", "status": "passed", "exit_code": 0},
        ],
        "regulator": {"outcome": "passed"},
    }
    base.update(overrides)
    return base


def _details_with_task(verification):
    task = {
        "id": "t1",
        "goal": "示例任务",
        "state": "verified",
        "worktree": {"lifecycle": "verified-unmerged", "diverged": False},
    }
    if verification is not None:
        task["verifications"] = [verification]
    return {"project": {"name": "demo"}, "worktrees": [task]}


class VerificationShadowTests(unittest.TestCase):
    def test_full_acceptance_and_regulator_leaves_minimal_shadow(self):
        shadow = verification_shadow(_verification())
        self.assertIn("未做全量验收", shadow)
        self.assertIn("边界测试未运行", shadow)
        self.assertIn("场景测试未配置", shadow)
        self.assertNotIn("无 AI 监管记录", shadow)
        self.assertFalse(any("静态检查" in item for item in shadow))

    def test_complete_acceptance_drops_full_gate_line(self):
        verification = _verification()
        verification["acceptance"]["complete"] = "passed"
        verification["acceptance"]["boundary"] = "passed"
        verification["acceptance"]["scenario"] = "passed"
        shadow = verification_shadow(verification)
        self.assertNotIn("未做全量验收", shadow)
        self.assertEqual(shadow, [])

    def test_skipped_checkers_are_named_and_capped(self):
        verification = _verification(
            checker_results=[
                {"id": f"check.s{i}", "stage": "floor", "status": "skipped", "exit_code": 0}
                for i in range(4)
            ]
        )
        shadow = verification_shadow(verification)
        line = next(item for item in shadow if item.startswith("跳过的检查："))
        self.assertIn("check.s0", line)
        self.assertIn("check.s1", line)
        self.assertNotIn("check.s2、", line)
        self.assertIn("等 4 项", line)

    def test_missing_regulator_record_is_shadowed(self):
        verification = _verification()
        del verification["regulator"]
        self.assertIn("无 AI 监管记录", verification_shadow(verification))

    def test_malformed_fields_degrade_silently(self):
        self.assertEqual(verification_shadow({}), ["无 AI 监管记录"])
        shadow = verification_shadow(
            {"acceptance": "broken", "checker_results": ["junk", {"status": "skipped"}], "regulator": {"outcome": "passed"}}
        )
        self.assertEqual(shadow, [])


class OpenTasksShadowTests(unittest.TestCase):
    def test_task_with_verification_carries_shadow(self):
        tasks = open_tasks(_details_with_task(_verification()))
        self.assertEqual(len(tasks), 1)
        self.assertIn("未做全量验收", tasks[0]["shadow"])
        self.assertIn("边界测试未运行", tasks[0]["shadow"])

    def test_task_without_verification_has_empty_shadow(self):
        tasks = open_tasks(_details_with_task(None))
        self.assertEqual(tasks[0]["shadow"], [])

    def test_non_dict_verification_is_ignored(self):
        details = _details_with_task(None)
        details["worktrees"][0]["verifications"] = ["junk"]
        tasks = open_tasks(details)
        self.assertEqual(tasks[0]["shadow"], [])

    def test_dashboard_model_passes_shadow_through(self):
        model = dashboard_model(_details_with_task(_verification()), {})
        self.assertIn("shadow", model["tasks"][0])
        self.assertIn("场景测试未配置", model["tasks"][0]["shadow"])
