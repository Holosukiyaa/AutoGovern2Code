"""动态房间预算（budgets.py）：系统算预算，用户被告知。

棘轮语义：首锚 实测×1.2；缩小自动收紧；增长不放宽；显式 policy 预算优先。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import bootstrap

from ag2c.budgets import HEADROOM, effective_budget_lines, load_budgets, recalibrate_budgets
from ag2c.checks import _budget_warnings
from ag2c.ledger import read_events
from ag2c.model import Card, Manifest, Target


def _card(room: str, *, budget_lines: int = 0) -> Card:
    return Card(
        card_id=room,
        card_type="knowledge",
        title=room,
        summary=room,
        scopes=(),
        checkers=(),
        references=(),
        budget_lines=budget_lines,
    )


class RecalibrateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp())
        (self._tmp / "src").mkdir(parents=True)
        (self._tmp / "state").mkdir(parents=True)
        self.manifest = Manifest(
            path=self._tmp / "manifest.json",
            project_id="test-proj",
            project_root=self._tmp,
            targets=(Target(target_id="app", path=".", governed_roots=("src",), excludes=()),),
            ledger_path=self._tmp / "ledger.jsonl",
            policy_path=self._tmp / "policy.json",
            state_dir=self._tmp / "state",
        )
        self.policy = mock.Mock()
        self.policy.card = lambda cid: _card(cid)

    def _write(self, rel: str, lines: int) -> None:
        (self._tmp / rel).write_text("x = 1\n" * lines, encoding="utf-8")

    def _recalibrate(self, files: list[str]) -> dict:
        fake_report = {"households": [{"id": "knowledge.room", "code_count": len(files), "files": files}]}
        with mock.patch("ag2c.households.census_report", return_value=fake_report):
            return recalibrate_budgets(self.manifest, self.policy, actor="test", reason="r")

    def test_first_observation_anchors_with_headroom(self) -> None:
        self._write("src/mod.py", 10)
        table = self._recalibrate(["app:src/mod.py"])
        row = table["rooms"][0]
        self.assertEqual("set", row["action"])
        self.assertEqual(10, row["measured_lines"])
        self.assertEqual(12, row["budget_lines"])  # ceil(10 × 1.2)
        self.assertEqual(12, effective_budget_lines(self.manifest, _card("knowledge.room")))

    def test_shrink_ratchets_down(self) -> None:
        self._write("src/mod.py", 10)
        self._recalibrate(["app:src/mod.py"])  # budget 12
        self._write("src/mod.py", 5)
        table = self._recalibrate(["app:src/mod.py"])
        row = table["rooms"][0]
        self.assertEqual("tightened", row["action"])
        self.assertEqual(6, row["budget_lines"])  # ceil(5 × 1.2)，棘轮收紧

    def test_growth_never_loosens(self) -> None:
        self._write("src/mod.py", 10)
        self._recalibrate(["app:src/mod.py"])  # budget 12
        self._write("src/mod.py", 11)  # 涨到 11（derived 14 > 12）
        table = self._recalibrate(["app:src/mod.py"])
        row = table["rooms"][0]
        self.assertEqual("kept", row["action"])
        self.assertEqual(12, row["budget_lines"])  # 不奖励增长

    def test_explicit_policy_budget_wins(self) -> None:
        self.policy.card = lambda cid: _card(cid, budget_lines=500)
        self._write("src/mod.py", 10)
        table = self._recalibrate(["app:src/mod.py"])
        self.assertEqual([], table["rooms"])  # 人工预算的房间动态机制不碰
        self.assertEqual(500, effective_budget_lines(self.manifest, _card("knowledge.room", budget_lines=500)))

    def test_empty_room_gets_no_budget(self) -> None:
        self._write("src/mod.py", 0)
        table = self._recalibrate(["app:src/mod.py"])
        self.assertEqual([], table["rooms"])

    def test_ledger_event_only_on_change(self) -> None:
        self._write("src/mod.py", 10)
        self._recalibrate(["app:src/mod.py"])
        events = [e for e in read_events(self.manifest.ledger_path) if e.get("event_type") == "budget-calibrated"]
        self.assertEqual(1, len(events))
        self.assertEqual("set", events[0]["payload"]["action"])
        self._recalibrate(["app:src/mod.py"])  # 无变化 → kept → 不再写事件
        events = [e for e in read_events(self.manifest.ledger_path) if e.get("event_type") == "budget-calibrated"]
        self.assertEqual(1, len(events))

    def test_corrupt_store_degrades_to_empty(self) -> None:
        (self._tmp / "state" / "budgets.json").write_text("{broken", encoding="utf-8")
        self.assertEqual({}, load_budgets(self.manifest))
        self.assertEqual(0, effective_budget_lines(self.manifest, _card("knowledge.room")))

    def test_corrupt_entry_type_degrades_to_zero(self) -> None:
        """坏仓的字段类型损坏（budget_lines 是字符串）也不穿透到 verify。"""
        (self._tmp / "state" / "budgets.json").write_text(
            json.dumps({"schema": "ag2c.budgets.v1", "rooms": {"knowledge.room": {"budget_lines": "abc"}}}),
            encoding="utf-8",
        )
        self.assertEqual(0, effective_budget_lines(self.manifest, _card("knowledge.room")))
        # 重标把坏条目当作无历史，重新首锚
        self._write("src/mod.py", 10)
        table = self._recalibrate(["app:src/mod.py"])
        self.assertEqual("set", table["rooms"][0]["action"])

    def test_dry_run_computes_without_persisting(self) -> None:
        """预览模式：出表但不落盘、不写账本（裸 CLI 命令的告知语义）。"""
        self._write("src/mod.py", 10)
        fake_report = {"households": [{"id": "knowledge.room", "code_count": 1, "files": ["app:src/mod.py"]}]}
        with mock.patch("ag2c.households.census_report", return_value=fake_report):
            table = recalibrate_budgets(self.manifest, self.policy, actor="", reason="", dry_run=True)
        self.assertEqual("set", table["rooms"][0]["action"])
        self.assertFalse((self._tmp / "state" / "budgets.json").exists())
        self.assertEqual([], read_events(self.manifest.ledger_path))

    def test_real_run_requires_actor_and_reason(self) -> None:
        from ag2c.errors import AG2CError

        self._write("src/mod.py", 10)
        fake_report = {"households": [{"id": "knowledge.room", "code_count": 1, "files": ["app:src/mod.py"]}]}
        with mock.patch("ag2c.households.census_report", return_value=fake_report):
            with self.assertRaises(AG2CError):
                recalibrate_budgets(self.manifest, self.policy, actor="", reason="")


class SettleBudgetHookTests(unittest.TestCase):
    """settle 自动重标：失败可观测（budgets_error），成功有账本事件。"""

    def test_settle_recalibrates_and_records(self) -> None:
        from ag2c.govern import settle_pending

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "proj"
            from support import git_project, write_project

            git_project(root)
            write_project(root, gated=True)
            with mock.patch("ag2c.govern.pending_updates", return_value={"items": []}):
                result = settle_pending(root, actor="test", reason="结算")
            self.assertIn("budgets", result["actions"])
            self.assertEqual("", result["budgets_error"])
            from ag2c.config import discover_manifest, load_manifest

            manifest = load_manifest(discover_manifest(root), project_root=root)
            events = [e for e in read_events(manifest.ledger_path) if e.get("event_type") == "budget-calibrated"]
            self.assertTrue(events)
            self.assertTrue((manifest.state_dir / "budgets.json").is_file())

    def test_settle_budget_failure_is_observable_not_fatal(self) -> None:
        from ag2c.govern import settle_pending

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "proj"
            from support import git_project, write_project

            git_project(root)
            write_project(root, gated=True)
            with mock.patch("ag2c.govern.pending_updates", return_value={"items": []}), mock.patch(
                "ag2c.budgets.recalibrate_budgets", side_effect=OSError("disk gone")
            ):
                result = settle_pending(root, actor="test", reason="结算")
            self.assertIn("budgets_error", result)
            self.assertIn("disk gone", result["budgets_error"])
            self.assertNotIn("budgets", result["actions"])

    def test_cli_bare_command_prints_preview_without_persisting(self) -> None:
        """裸 `ag2c govern budget-recalibrate`：打出预算表但不落盘（告知优先）。"""
        import io
        import os

        from ag2c.cli import main

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "proj"
            from support import git_project, write_project

            git_project(root)
            write_project(root, gated=True)
            previous = Path.cwd()
            stdout = io.StringIO()
            try:
                os.chdir(root)
                with mock.patch("sys.stdout", stdout):
                    exit_code = main(["govern", "budget-recalibrate"])
            finally:
                os.chdir(previous)
            self.assertEqual(0, exit_code)
            self.assertIn("预算", stdout.getvalue())
            self.assertIn("预览", stdout.getvalue())
            self.assertFalse((root / ".ag2c" / "state" / "budgets.json").exists())


class DynamicBudgetWarningTests(unittest.TestCase):
    """_budget_warnings 的行预算由动态仓供电（显式优先）。"""

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp())
        (self._tmp / "src").mkdir(parents=True)
        (self._tmp / "state").mkdir(parents=True)
        self.manifest = Manifest(
            path=self._tmp / "manifest.json",
            project_id="test-proj",
            project_root=self._tmp,
            targets=(Target(target_id="app", path=".", governed_roots=("src",), excludes=()),),
            ledger_path=self._tmp / "ledger.jsonl",
            policy_path=self._tmp / "policy.json",
            state_dir=self._tmp / "state",
        )

    def _warnings(self, files: list[str]) -> list[dict]:
        policy = mock.Mock()
        policy.card = lambda cid: _card(cid)
        fake_report = {"households": [{"id": "knowledge.room", "code_count": len(files), "files": files}]}
        with mock.patch("ag2c.households.census_report", return_value=fake_report):
            return _budget_warnings(self.manifest, policy, {})

    def test_dynamic_budget_feeds_over_budget_warning(self) -> None:
        (self._tmp / "src" / "mod.py").write_text("x = 1\n" * 10, encoding="utf-8")
        policy = mock.Mock()
        policy.card = lambda cid: _card(cid)
        fake = {"households": [{"id": "knowledge.room", "code_count": 1, "files": ["app:src/mod.py"]}]}
        with mock.patch("ag2c.households.census_report", return_value=fake):
            recalibrate_budgets(self.manifest, policy, actor="t", reason="锚定")  # budget 12
        # 长到 13 行：超动态预算 12 → 报警
        (self._tmp / "src" / "mod.py").write_text("x = 1\n" * 13, encoding="utf-8")
        warnings = self._warnings(["app:src/mod.py"])
        lines = [w for w in warnings if w.get("dimension") == "lines"]
        self.assertEqual(1, len(lines))
        self.assertIn("预算 12", lines[0]["detail"])

    def test_no_dynamic_no_explicit_no_warning(self) -> None:
        (self._tmp / "src" / "mod.py").write_text("x = 1\n" * 500, encoding="utf-8")
        self.assertEqual([], self._warnings(["app:src/mod.py"]))


class HouseholdBudgetLinesTests(unittest.TestCase):
    """govern household 的显式行预算：写入 / 省略保留 / 0 清除 / 负数拒绝。

    死锁教训（2026-09-10）：动态预算棘轮只下不上，家庭房间刻意增长后
    没有任何合法通道抬预算，升级门全局锁死——此参数就是那条通道。
    """

    def setUp(self) -> None:
        from support import git_project, write_project

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = git_project(Path(self._tmp.name) / "demo")
        write_project(self.root)

    def _register(self, **overrides):
        from ag2c.household_commands import register_household

        params = dict(
            card_id="knowledge.api-docs",
            title="api docs",
            summary="docs household for budget tests",
            includes=["docs/**"],
            excludes=[],
            floors=["floor.api"],
            capability="docs",
            implementation="docs.exploring",
            status="current",
            actor="test",
            reason="household budget test",
        )
        params.update(overrides)
        return register_household(self.root, **params)

    def _budget_of(self, card_id: str = "knowledge.api-docs") -> int:
        from ag2c.config import discover_manifest, load_manifest, load_policy

        manifest = load_manifest(discover_manifest(self.root), project_root=self.root)
        card = load_policy(manifest).card(card_id)
        return card.budget_lines

    def test_explicit_budget_written(self) -> None:
        self._register(budget_lines=500)
        self.assertEqual(500, self._budget_of())

    def test_omitted_budget_preserves_existing(self) -> None:
        self._register(budget_lines=500)
        self._register(summary="updated summary, budget omitted")
        self.assertEqual(500, self._budget_of())

    def test_zero_clears_explicit_budget(self) -> None:
        self._register(budget_lines=500)
        self._register(budget_lines=0)
        self.assertEqual(0, self._budget_of())

    def test_negative_budget_rejected(self) -> None:
        from ag2c.errors import AG2CError

        with self.assertRaises(AG2CError):
            self._register(budget_lines=-1)

    def test_explicit_budget_clears_over_budget_warning(self) -> None:
        """场景验收（画像承诺②）：写入前 _budget_warnings 报 key=...:lines
        over-budget；用新参数抬显式预算后，同一 key 从警告里消失。"""
        from ag2c.config import discover_manifest, load_manifest, load_policy

        doc = self.root / "docs" / "a.md"
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text("line\n" * 20, encoding="utf-8")
        self._register(budget_lines=10)
        manifest = load_manifest(discover_manifest(self.root), project_root=self.root)
        fake_report = {"households": [{"id": "knowledge.api-docs", "code_count": 1, "files": ["app:docs/a.md"]}]}

        def warning_keys() -> list[str]:
            policy = load_policy(manifest)
            with mock.patch("ag2c.households.census_report", return_value=fake_report):
                return [w["key"] for w in _budget_warnings(manifest, policy, {})]

        self.assertIn("knowledge.api-docs:lines", warning_keys())  # 设置前：超预算
        self._register(budget_lines=500)
        self.assertNotIn("knowledge.api-docs:lines", warning_keys())  # 写入后：警告消失


if __name__ == "__main__":
    unittest.main()
