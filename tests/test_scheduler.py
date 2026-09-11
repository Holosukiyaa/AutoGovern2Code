"""调度器 Phase 1 影子模式：shadow_plan 纯函数与 verify 接线。

影子不真跳——plan 只落 verify 记录与账本事件，观察「本会跳过什么」。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import bootstrap  # noqa: F401

from ag2c.ledger import read_events
from ag2c.scheduler import SHADOW_PLAN_SCHEMA, shadow_plan


def _verification_event(*, change_digest: str, passed: bool, results: list[dict]) -> dict:
    return {
        "event_type": "task-verification",
        "payload": {
            "task_id": "t-x",
            "passed": passed,
            "change_digest": change_digest,
            "checker_results": results,
        },
    }


class ShadowPlanTests(unittest.TestCase):
    def test_cache_hit_would_skip(self) -> None:
        events = [
            _verification_event(
                change_digest="d1",
                passed=True,
                results=[{"id": "check.python", "status": "passed"}, {"id": "check.diff", "status": "passed"}],
            )
        ]
        plan = shadow_plan(
            planned_checker_ids=["check.python", "check.diff"],
            all_checker_ids=["check.python", "check.diff"],
            change_digest="d1",
            events=events,
        )
        self.assertEqual(SHADOW_PLAN_SCHEMA, plan["schema"])
        self.assertEqual("shadow", plan["mode"])
        self.assertEqual(["check.diff", "check.python"], sorted(plan["would_skip"]))
        for entry in plan["entries"]:
            self.assertEqual("skip", entry["shadow"])
            self.assertEqual(["unchanged-inputs"], entry["reasons"])

    def test_different_digest_runs(self) -> None:
        events = [
            _verification_event(change_digest="d1", passed=True, results=[{"id": "check.python", "status": "passed"}])
        ]
        plan = shadow_plan(
            planned_checker_ids=["check.python"],
            all_checker_ids=["check.python"],
            change_digest="d2",
            events=events,
        )
        self.assertEqual([], plan["would_skip"])
        self.assertEqual("run", plan["entries"][0]["shadow"])
        self.assertEqual(["slice-selected"], plan["entries"][0]["reasons"])

    def test_failed_history_does_not_skip(self) -> None:
        events = [
            _verification_event(change_digest="d1", passed=False, results=[{"id": "check.python", "status": "failed"}])
        ]
        plan = shadow_plan(
            planned_checker_ids=["check.python"],
            all_checker_ids=["check.python"],
            change_digest="d1",
            events=events,
        )
        self.assertEqual([], plan["would_skip"])
        self.assertEqual("run", plan["entries"][0]["shadow"])

    def test_unplanned_checker_skips_as_not_in_slice(self) -> None:
        plan = shadow_plan(
            planned_checker_ids=["check.python"],
            all_checker_ids=["check.python", "check.suite-gui"],
            change_digest="d1",
            events=[],
        )
        gui = next(entry for entry in plan["entries"] if entry["id"] == "check.suite-gui")
        self.assertFalse(gui["planned"])
        self.assertEqual("skip", gui["shadow"])
        self.assertEqual(["not-in-slice"], gui["reasons"])
        # 未计划的跳过是影子与现实的一致意见，不算「本会跳过」的差额
        self.assertEqual([], plan["would_skip"])

    def test_green_history_missing_this_checker_does_not_skip(self) -> None:
        events = [
            _verification_event(change_digest="d1", passed=True, results=[{"id": "check.diff", "status": "passed"}])
        ]
        plan = shadow_plan(
            planned_checker_ids=["check.python"],
            all_checker_ids=["check.python"],
            change_digest="d1",
            events=events,
        )
        self.assertEqual([], plan["would_skip"])
        self.assertEqual("run", plan["entries"][0]["shadow"])


class ShadowPlanWiringTests(unittest.TestCase):
    """verify_task 接线：shadow_plan 落 verification 记录与账本事件；重试同 digest 命中缓存。"""

    def _project(self, base: Path) -> Path:
        """生产拓扑夹具（enroll 外部存储 + gated policy），与 test_verify_costs 同型。"""
        import os
        import shutil
        import subprocess

        from ag2c.enrollment import enroll_project
        from support import git_project, write_project

        root = git_project(base / "proj")
        (root / "src" / "api").mkdir(parents=True)
        (root / "src" / "worker").mkdir(parents=True)
        (root / "src" / "api" / "service.py").write_text("VALUE = 'api'\n", encoding="utf-8")
        (root / "src" / "worker" / "job.py").write_text("VALUE = 'worker'\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "--all"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(root), "commit", "-m", "rooms"], check=True, capture_output=True)
        with mock.patch.dict(os.environ, {"AG2C_DATA_ROOT": str(base / "ag2c-data")}, clear=False):
            result = enroll_project(root, skill_root=base / "skills", harnesses=("agents",))
        store = Path(result["store"])
        scratch = base / "scratch"
        write_project(scratch, gated=True)
        shutil.copy2(scratch / ".ag2c" / "policy.json", store / "policy.json")
        return root

    def test_shadow_plan_lands_in_record_and_ledger(self) -> None:
        from ag2c.config import discover_manifest, load_manifest
        from ag2c.tasks import start_task, verify_task
        from support import record_census

        with tempfile.TemporaryDirectory() as tmp:
            root = self._project(Path(tmp))
            portrait = (
                "Done looks like: 服务函数返回值变更。Surfaces: verify 通过。"
                "Out of result: 不动其他模块。验证层: 机器验证 tests 套件全绿，输出片段进 finish proof。无加料。"
            )
            task = start_task(
                root,
                goal="change",
                path_specs=["app:src/api/service.py"],
                contract_specs=[],
                portrait=portrait,
                worktree_root=root.parent / "worktrees",
            )
            worktree = Path(task["worktree"]["path"])
            service = worktree / "src" / "api" / "service.py"
            service.write_text(service.read_text(encoding="utf-8") + "# touched\n", encoding="utf-8")
            record_census(worktree)

            first = verify_task(worktree)
            self.assertTrue(first["passed"])
            plan = first["verification"]["shadow_plan"]
            self.assertEqual("shadow", plan["mode"])
            self.assertEqual([], plan["would_skip"])  # 首跑无历史，无缓存命中
            self.assertTrue(plan["entries"])

            # 账本事件 payload 带着同一份影子计划
            canonical_manifest = load_manifest(discover_manifest(root), project_root=root)
            events = [
                event
                for event in read_events(canonical_manifest.ledger_path)
                if event.get("event_type") == "task-verification"
            ]
            self.assertEqual(1, len(events))
            self.assertEqual(plan["change_digest"], events[0]["payload"]["shadow_plan"]["change_digest"])

            # 同 digest 重试：影子说「本会全跳」，现实仍全跑
            second = verify_task(worktree)
            self.assertTrue(second["passed"])
            rerun = second["verification"]["shadow_plan"]
            self.assertTrue(rerun["would_skip"])
            self.assertEqual(
                sorted(item["id"] for item in second["verification"]["checker_results"]),
                sorted(rerun["would_skip"]),
            )


if __name__ == "__main__":
    unittest.main()
