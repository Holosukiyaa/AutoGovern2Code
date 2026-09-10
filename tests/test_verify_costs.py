"""验证成本治理（verify_costs.py）：verify 自身的预算与计量。

计量：checker 耗时从账本 check-run 事件可查询；预算：首锚 实测×1.5（近5次
最大）、棘轮只紧不松、显式 budget_seconds 优先、无历史/坏仓不报警；超支
产出 over-budget 警告进 9.7 管道；全量验收需任务级显式声明（申请预算）。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import bootstrap  # noqa: F401

from ag2c.ledger import append_event, read_events
from ag2c.model import Checker, Manifest, Target
from ag2c.verify_costs import (
    MIN_BUDGET_SECONDS,
    VERIFY_BUDGETS_SCHEMA,
    VERIFY_HEADROOM,
    checker_duration_history,
    effective_budget_seconds,
    load_verify_budgets,
    measured_seconds,
    recalibrate_verify_budgets,
    verify_budget_warnings,
)


def _checker(checker_id: str, *, budget_seconds: float = 0.0) -> Checker:
    return Checker(checker_id, "floor", None, ("python", "-c", "pass"), ".", 300, budget_seconds=budget_seconds)


def _manifest(root: Path) -> Manifest:
    (root / "state").mkdir(parents=True, exist_ok=True)
    return Manifest(
        path=root / "manifest.json",
        project_id="test-proj",
        project_root=root,
        targets=(Target(target_id="app", path=".", governed_roots=("src",), excludes=()),),
        ledger_path=root / "ledger.jsonl",
        policy_path=root / "policy.json",
        state_dir=root / "state",
    )


def _policy(*checkers: Checker):
    policy = mock.Mock()
    policy.checkers = list(checkers)
    return policy


def _record_run(manifest: Manifest, runs: dict[str, float]) -> None:
    """写一条 check-run 账本事件：runs = {checker_id: 秒}。"""
    append_event(
        manifest.ledger_path,
        "check-run",
        {"results": [{"id": cid, "stage": "floor", "status": "passed", "duration_ms": seconds * 1000} for cid, seconds in runs.items()]},
    )


class DurationHistoryTests(unittest.TestCase):
    def test_history_queryable_from_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = _manifest(Path(tmp))
            _record_run(manifest, {"check.a": 10.0, "check.b": 3.0})
            _record_run(manifest, {"check.a": 12.0})
            history = checker_duration_history(manifest)
            self.assertEqual([10.0, 12.0], history["check.a"])
            self.assertEqual([3.0], history["check.b"])

    def test_history_ignores_junk_and_other_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = _manifest(Path(tmp))
            append_event(manifest.ledger_path, "task-started", {"task_id": "t1"})
            append_event(manifest.ledger_path, "check-run", {"results": [{"id": "check.a", "duration_ms": 0}, {"id": "", "duration_ms": 5}, "junk"]})
            self.assertEqual({}, checker_duration_history(manifest))

    def test_missing_ledger_degrades_to_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual({}, checker_duration_history(_manifest(Path(tmp))))

    def test_measured_is_window_max_not_latest(self) -> None:
        # 最近一次的快运行不能锚出低预算——取近 5 次最大（噪声上界）
        self.assertEqual(20.0, measured_seconds([20.0, 10.0, 5.0]))
        self.assertEqual(0.0, measured_seconds([]))
        self.assertEqual(6.0, measured_seconds([1.0, 8.0, 2.0, 3.0, 4.0, 5.0, 6.0]))  # 窗口只看近 5 次：8.0 在窗外


class RecalibrateTests(unittest.TestCase):
    def test_first_observation_anchors_with_headroom(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = _manifest(Path(tmp))
            _record_run(manifest, {"check.a": 100.0})
            table = recalibrate_verify_budgets(manifest, _policy(_checker("check.a")), actor="t", reason="锚定")
            row = table["checkers"][0]
            self.assertEqual("set", row["action"])
            self.assertEqual(100.0, row["measured_seconds"])
            self.assertEqual(int(100 * VERIFY_HEADROOM), row["budget_seconds"])
            self.assertEqual(float(int(100 * VERIFY_HEADROOM)), effective_budget_seconds(manifest, _checker("check.a")))

    def test_min_budget_floor_for_tiny_checkers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = _manifest(Path(tmp))
            _record_run(manifest, {"check.a": 1.0})
            table = recalibrate_verify_budgets(manifest, _policy(_checker("check.a")), actor="t", reason="锚定")
            self.assertEqual(float(MIN_BUDGET_SECONDS), table["checkers"][0]["budget_seconds"])

    def test_shrink_ratchets_down_growth_never_loosens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = _manifest(Path(tmp))
            policy = _policy(_checker("check.a"))
            _record_run(manifest, {"check.a": 100.0})
            recalibrate_verify_budgets(manifest, policy, actor="t", reason="锚定")  # 150
            _record_run(manifest, {"check.a": 10.0})
            # 窗口含旧的 100 → 实测仍 100 → kept；连续 5 次小运行后窗口只剩 10 → 收紧到 15
            for _ in range(5):
                _record_run(manifest, {"check.a": 10.0})
            table = recalibrate_verify_budgets(manifest, policy, actor="t", reason="重标")
            self.assertEqual("tightened", table["checkers"][0]["action"])
            self.assertEqual(15.0, table["checkers"][0]["budget_seconds"])
            # 增长不放宽：实测涨到 20（derived 30 > 15）→ kept 15
            for _ in range(5):
                _record_run(manifest, {"check.a": 20.0})
            table = recalibrate_verify_budgets(manifest, policy, actor="t", reason="重标")
            self.assertEqual("kept", table["checkers"][0]["action"])
            self.assertEqual(15.0, table["checkers"][0]["budget_seconds"])

    def test_explicit_policy_budget_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = _manifest(Path(tmp))
            _record_run(manifest, {"check.a": 100.0})
            table = recalibrate_verify_budgets(manifest, _policy(_checker("check.a", budget_seconds=500.0)), actor="t", reason="锚定")
            self.assertEqual([], table["checkers"])  # 人工预算的 checker 动态机制不碰
            self.assertEqual(500.0, effective_budget_seconds(manifest, _checker("check.a", budget_seconds=500.0)))

    def test_no_history_no_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = _manifest(Path(tmp))
            table = recalibrate_verify_budgets(manifest, _policy(_checker("check.a")), actor="t", reason="锚定")
            self.assertEqual([], table["checkers"])
            self.assertEqual(0.0, effective_budget_seconds(manifest, _checker("check.a")))

    def test_corrupt_store_degrades_to_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = _manifest(Path(tmp))
            (manifest.state_dir / "verify-budgets.json").write_text("{broken", encoding="utf-8")
            self.assertEqual({}, load_verify_budgets(manifest))
            self.assertEqual(0.0, effective_budget_seconds(manifest, _checker("check.a")))

    def test_corrupt_entry_type_degrades_to_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = _manifest(Path(tmp))
            (manifest.state_dir / "verify-budgets.json").write_text(
                json.dumps({"schema": VERIFY_BUDGETS_SCHEMA, "checkers": {"check.a": {"budget_seconds": "abc"}}}),
                encoding="utf-8",
            )
            self.assertEqual(0.0, effective_budget_seconds(manifest, _checker("check.a")))

    def test_dry_run_computes_without_persisting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = _manifest(Path(tmp))
            _record_run(manifest, {"check.a": 100.0})
            table = recalibrate_verify_budgets(manifest, _policy(_checker("check.a")), actor="", reason="", dry_run=True)
            self.assertEqual("set", table["checkers"][0]["action"])
            self.assertFalse((manifest.state_dir / "verify-budgets.json").exists())
            self.assertEqual(["check-run"], [e.get("event_type") for e in read_events(manifest.ledger_path)])

    def test_real_run_requires_actor_and_reason(self) -> None:
        from ag2c.errors import AG2CError

        with tempfile.TemporaryDirectory() as tmp:
            manifest = _manifest(Path(tmp))
            _record_run(manifest, {"check.a": 100.0})
            with self.assertRaises(AG2CError):
                recalibrate_verify_budgets(manifest, _policy(_checker("check.a")), actor="", reason="")

    def test_ledger_event_only_on_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = _manifest(Path(tmp))
            policy = _policy(_checker("check.a"))
            _record_run(manifest, {"check.a": 100.0})
            recalibrate_verify_budgets(manifest, policy, actor="t", reason="锚定")
            events = [e for e in read_events(manifest.ledger_path) if e.get("event_type") == "verify-budget-calibrated"]
            self.assertEqual(1, len(events))
            self.assertEqual("set", events[0]["payload"]["action"])
            recalibrate_verify_budgets(manifest, policy, actor="t", reason="再标")  # kept → 不再写
            events = [e for e in read_events(manifest.ledger_path) if e.get("event_type") == "verify-budget-calibrated"]
            self.assertEqual(1, len(events))


class VerifyBudgetWarningTests(unittest.TestCase):
    def test_over_budget_warns_with_escalatable_kind(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = _manifest(Path(tmp))
            policy = _policy(_checker("check.a"))
            _record_run(manifest, {"check.a": 100.0})
            recalibrate_verify_budgets(manifest, policy, actor="t", reason="锚定")  # 预算 150
            warnings = verify_budget_warnings(manifest, policy, [{"id": "check.a", "duration_ms": 200_000}])
            self.assertEqual(1, len(warnings))
            self.assertEqual("over-budget", warnings[0]["kind"])  # 9.7 可升级种类
            self.assertEqual("check.a:seconds", warnings[0]["key"])
            self.assertIn("200.0s", warnings[0]["detail"])
            self.assertIn("150", warnings[0]["detail"])

    def test_under_budget_silent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = _manifest(Path(tmp))
            policy = _policy(_checker("check.a"))
            _record_run(manifest, {"check.a": 100.0})
            recalibrate_verify_budgets(manifest, policy, actor="t", reason="锚定")
            self.assertEqual([], verify_budget_warnings(manifest, policy, [{"id": "check.a", "duration_ms": 100_000}]))

    def test_no_budget_no_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = _manifest(Path(tmp))
            policy = _policy(_checker("check.a"))
            self.assertEqual([], verify_budget_warnings(manifest, policy, [{"id": "check.a", "duration_ms": 999_000_000}]))

    def test_explicit_budget_also_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = _manifest(Path(tmp))
            policy = _policy(_checker("check.a", budget_seconds=10.0))
            warnings = verify_budget_warnings(manifest, policy, [{"id": "check.a", "duration_ms": 20_000}])
            self.assertEqual(1, len(warnings))


class SettleVerifyBudgetHookTests(unittest.TestCase):
    """settle 自动重标验证预算：成功进 actions，失败可观测不致命。"""

    def _gated_project(self, base: Path) -> Path:
        from support import git_project, write_project

        root = git_project(base / "proj")
        write_project(root, gated=True)
        return root

    def test_settle_recalibrates_verify_budgets(self) -> None:
        from ag2c.config import discover_manifest, load_manifest
        from ag2c.govern import settle_pending

        with tempfile.TemporaryDirectory() as tmp:
            root = self._gated_project(Path(tmp))
            manifest = load_manifest(discover_manifest(root), project_root=root)
            _record_run(manifest, {"check.floor": 42.0})
            with mock.patch("ag2c.govern.pending_updates", return_value={"items": []}):
                result = settle_pending(root, actor="test", reason="结算")
            self.assertEqual("", result["verify_budgets_error"])
            self.assertIn("verify-budgets", result["actions"])
            self.assertTrue((manifest.state_dir / "verify-budgets.json").is_file())
            events = [e for e in read_events(manifest.ledger_path) if e.get("event_type") == "verify-budget-calibrated"]
            self.assertTrue(events)

    def test_settle_verify_budget_failure_is_observable_not_fatal(self) -> None:
        from ag2c.govern import settle_pending

        with tempfile.TemporaryDirectory() as tmp:
            root = self._gated_project(Path(tmp))
            with mock.patch("ag2c.govern.pending_updates", return_value={"items": []}), mock.patch(
                "ag2c.verify_costs.recalibrate_verify_budgets", side_effect=OSError("disk gone")
            ):
                result = settle_pending(root, actor="test", reason="结算")
            self.assertIn("disk gone", result["verify_budgets_error"])
            self.assertNotIn("verify-budgets", result["actions"])

    def test_cli_bare_command_prints_preview_without_persisting(self) -> None:
        """裸 `ag2c govern verify-budget`：打出预算表但不落盘（告知优先）。"""
        import io
        import os

        from ag2c.cli import main
        from ag2c.config import discover_manifest, load_manifest

        with tempfile.TemporaryDirectory() as tmp:
            root = self._gated_project(Path(tmp))
            manifest = load_manifest(discover_manifest(root), project_root=root)
            _record_run(manifest, {"check.floor": 42.0})
            previous = Path.cwd()
            stdout = io.StringIO()
            try:
                os.chdir(root)
                with mock.patch("sys.stdout", stdout):
                    exit_code = main(["govern", "verify-budget"])
            finally:
                os.chdir(previous)
            self.assertEqual(0, exit_code)
            self.assertIn("check.floor", stdout.getvalue())
            self.assertIn("预览", stdout.getvalue())
            self.assertFalse((manifest.state_dir / "verify-budgets.json").exists())

    def test_cli_empty_history_prints_empty_state(self) -> None:
        import io
        import os

        from ag2c.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = self._gated_project(Path(tmp))
            previous = Path.cwd()
            stdout = io.StringIO()
            try:
                os.chdir(root)
                with mock.patch("sys.stdout", stdout):
                    exit_code = main(["govern", "verify-budget"])
            finally:
                os.chdir(previous)
            self.assertEqual(0, exit_code)
            self.assertIn("没有可预算的 checker", stdout.getvalue())


class FullScanDeclarationTests(unittest.TestCase):
    """全量验收的任务级显式声明（申请预算语义）：governance 变化不再静默升级全量。"""

    def _project(self, base: Path) -> Path:
        """生产拓扑夹具（enroll 外部存储 + gated policy），与 test_tasks.AutoRefreshTests 同型。"""
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

    def _start(self, root: Path):
        from ag2c.tasks import start_task

        portrait = (
            "Done looks like: 服务函数返回值变更。Surfaces: verify 通过。"
            "Out of result: 不动其他模块。验证层: 机器验证 tests 套件全绿，输出片段进 finish proof。无加料。"
        )
        return start_task(
            root,
            goal="change",
            path_specs=["app:src/api/service.py"],
            contract_specs=[],
            portrait=portrait,
            worktree_root=root.parent / "worktrees",
        )

    def _touch_and_census(self, root: Path, worktree: Path) -> None:
        from support import record_census

        service = worktree / "src" / "api" / "service.py"
        service.write_text(service.read_text(encoding="utf-8") + "# touched by task\n", encoding="utf-8")
        record_census(worktree)

    def _mutate_policy(self, root: Path) -> None:
        """任务期间改 policy（调 timeout），触发 governance_changed。"""
        from ag2c.config import discover_manifest, load_manifest

        manifest = load_manifest(discover_manifest(root), project_root=root)
        raw = json.loads(manifest.policy_path.read_text(encoding="utf-8"))
        raw["checkers"][0]["timeout"] = 301
        manifest.policy_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def test_verify_refuses_undeclared_full_scan(self) -> None:
        from ag2c.errors import AG2CError
        from ag2c.tasks import verify_task

        with tempfile.TemporaryDirectory() as tmp:
            root = self._project(Path(tmp))
            task = self._start(root)
            worktree = Path(task["worktree"]["path"])
            self._touch_and_census(root, worktree)
            self._mutate_policy(root)
            with self.assertRaisesRegex(AG2CError, "declare --full-scan"):
                verify_task(worktree)
            kinds = [item["kind"] for item in self._record(root, task["id"])["interventions"]]
            self.assertIn("governance-changed", kinds)

    def test_declared_full_scan_lets_verify_pass(self) -> None:
        from ag2c.tasks import declare_full_scan, verify_task

        with tempfile.TemporaryDirectory() as tmp:
            root = self._project(Path(tmp))
            task = self._start(root)
            worktree = Path(task["worktree"]["path"])
            self._touch_and_census(root, worktree)
            self._mutate_policy(root)
            result = declare_full_scan(worktree, reason="policy 变了，本次必须全量")
            self.assertTrue(result["full_scan"]["declared"])
            report = verify_task(worktree)
            self.assertTrue(report["passed"])
            kinds = [item["kind"] for item in self._record(root, task["id"])["interventions"]]
            self.assertIn("full-scan-declared", kinds)

    def test_start_all_counts_as_declaration(self) -> None:
        from ag2c.tasks import start_task, verify_task

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
                all_mode=True,
            )
            worktree = Path(task["worktree"]["path"])
            self._touch_and_census(root, worktree)
            self._mutate_policy(root)
            self.assertTrue(verify_task(worktree)["passed"])  # --all 开工即声明，无需再申报

    def test_declare_full_scan_requires_reason(self) -> None:
        from ag2c.errors import AG2CError
        from ag2c.tasks import declare_full_scan

        with tempfile.TemporaryDirectory() as tmp:
            root = self._project(Path(tmp))
            task = self._start(root)
            with self.assertRaises(AG2CError):
                declare_full_scan(Path(task["worktree"]["path"]), reason="  ")

    def _record(self, root: Path, task_id: str) -> dict:
        from ag2c.config import discover_manifest, load_manifest

        manifest = load_manifest(discover_manifest(root), project_root=root)
        return json.loads((manifest.state_dir / "tasks" / f"{task_id}.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
