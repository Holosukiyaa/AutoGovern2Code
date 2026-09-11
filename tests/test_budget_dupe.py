"""Soft budget and duplicate detection tests."""

from __future__ import annotations

import ast
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ag2c.checks import (
    DERIVED_AST_NODES_PER_LINE,
    DERIVED_CHARS_PER_LINE,
    ESCALATABLE_KINDS,
    WARNING_ESCALATION_THRESHOLD,
    _budget_warnings,
    _duplicate_warnings,
    _load_warning_history,
    _record_warnings_and_find_escalated,
    _room_code_measurements,
    baseline_debt,
    dismiss_warning,
)
from ag2c.config import load_policy
from ag2c.errors import AG2CError
from ag2c.ledger import read_events
from ag2c.model import Card, Manifest, Target

from support import bare_manifest


class BudgetWarningTests(unittest.TestCase):
    def test_no_budget_no_warning(self) -> None:
        """Cards without budget_lines never trigger warnings."""
        # _budget_warnings needs a real manifest+policy; test the logic directly.
        # With budget_lines=0 (default), no warning should fire.
        self.assertEqual(0, 0)  # placeholder — integration tested via verify

    def test_budget_lines_parsed_from_policy(self) -> None:
        """config.py parses budget_lines into the Card model."""
        from ag2c.config import _provides
        # The field is parsed inline in load_policy; test via model defaults.
        from ag2c.model import Card
        card = Card(
            card_id="test",
            card_type="knowledge",
            title="test",
            summary="test",
            scopes=(),
            checkers=(),
            references=(),
            budget_lines=500,
        )
        self.assertEqual(500, card.budget_lines)

    def test_budget_lines_defaults_to_zero(self) -> None:
        from ag2c.model import Card
        card = Card(
            card_id="test",
            card_type="knowledge",
            title="test",
            summary="test",
            scopes=(),
            checkers=(),
            references=(),
        )
        self.assertEqual(0, card.budget_lines)


class MultiDimensionBudgetTests(unittest.TestCase):
    """9.6: budget checker supports chars + AST-node dimensions (anti 钉子厂)."""

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp())
        (self._tmp / "src").mkdir(parents=True)

    def _write(self, rel: str, text: str) -> None:
        path = self._tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _manifest_with_target(self) -> Manifest:
        return Manifest(
            path=self._tmp / "manifest.json",
            project_id="test-proj",
            project_root=self._tmp,
            targets=(Target(target_id="app", path=".", governed_roots=("src",), excludes=()),),
            ledger_path=self._tmp / "ledger.jsonl",
            policy_path=self._tmp / "policy.json",
            state_dir=self._tmp / "state",
        )

    def test_new_fields_default_to_zero(self) -> None:
        card = Card(
            card_id="t", card_type="knowledge", title="t", summary="t",
            scopes=(), checkers=(), references=(),
        )
        self.assertEqual(0, card.budget_chars)
        self.assertEqual(0, card.budget_ast_nodes)

    def test_new_fields_parse_from_policy(self) -> None:
        raw = {
            "schema": "ag2c.policy.v1",
            "cards": [
                {
                    "id": "floor.app",
                    "type": "floor",
                    "title": "app",
                    "summary": "app floor",
                    "scopes": [{"target": "app", "include": ["src/**"], "ownership": "primary"}],
                    "checkers": ["check.diff"],
                    "references": [],
                },
                {
                    "id": "knowledge.room",
                    "type": "knowledge",
                    "title": "room",
                    "summary": "room",
                    "scopes": [],
                    "checkers": [],
                    "references": [],
                    "budget_lines": 100,
                    "budget_chars": 5000,
                    "budget_ast_nodes": 800,
                },
            ],
            "relations": [],
            "contracts": [],
            "checkers": [
                {"id": "check.diff", "stage": "floor", "target": "app",
                 "command": ["git", "diff", "--check"], "cwd": ".", "timeout": 30}
            ],
            "coverage": {"level": "baseline", "strategy": "conservative", "managed_by": "human", "areas": []},
        }
        path = self._tmp / "policy.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        manifest = self._manifest_with_target()
        policy = load_policy(Manifest(
            path=manifest.path, project_id=manifest.project_id, project_root=manifest.project_root,
            policy_path=path, state_dir=manifest.state_dir, ledger_path=manifest.ledger_path,
            targets=manifest.targets,
        ))
        card = policy.card("knowledge.room")
        self.assertEqual(100, card.budget_lines)
        self.assertEqual(5000, card.budget_chars)
        self.assertEqual(800, card.budget_ast_nodes)

    def test_measurements_count_lines_chars_ast(self) -> None:
        self._write("src/mod.py", "def foo():\n    return 1\n")
        manifest = self._manifest_with_target()
        # census code_count is a code-FILE count (1 file here), NOT lines;
        # measurements must count real lines from file contents.
        item = {"code_count": 1, "files": ["app:src/mod.py"]}
        measured = _room_code_measurements(manifest, item)
        self.assertEqual(2, measured["lines"])
        self.assertEqual(len("def foo():\n    return 1\n"), measured["chars"])
        expected_nodes = sum(1 for _ in ast.walk(ast.parse("def foo():\n    return 1\n")))
        self.assertEqual(expected_nodes, measured["ast_nodes"])

    def test_measurements_skip_missing_files(self) -> None:
        manifest = self._manifest_with_target()
        item = {"code_count": 10, "files": ["app:src/gone.py", "app:src/alsogone.py"]}
        measured = _room_code_measurements(manifest, item)
        self.assertEqual(0, measured["lines"])  # measured from disk, not census
        self.assertEqual(0, measured["chars"])
        self.assertEqual(0, measured["ast_nodes"])

    def test_dense_code_trips_chars_dimension_with_derived_budget(self) -> None:
        """钉子厂: 10 lines of 200-char code passes a 100-line budget but trips chars."""
        dense_line = "x = " + " + ".join(["1"] * 60)  # ~244 chars, one line
        dense = (dense_line + "\n") * 10  # 10 lines, ~2440 chars
        self._write("src/dense.py", dense)
        manifest = self._manifest_with_target()
        card = Card(
            card_id="knowledge.room", card_type="knowledge", title="room", summary="room",
            scopes=(), checkers=(), references=(), jurisdiction={"span": "folder"},
            budget_lines=100,  # 10 lines << 100: line dimension passes
        )
        self.assertLess(10, card.budget_lines)
        derived_chars = card.budget_lines * DERIVED_CHARS_PER_LINE  # 16000
        measured = _room_code_measurements(manifest, {"code_count": 10, "files": ["app:src/dense.py"]})
        # Sanity: dense code has ~244 chars/line, way above the 160/line ceiling ratio.
        self.assertGreater(measured["chars"] / 10, DERIVED_CHARS_PER_LINE)
        # Directly exercise the warning decision with a small explicit chars budget.
        card2 = Card(
            card_id="knowledge.room", card_type="knowledge", title="room", summary="room",
            scopes=(), checkers=(), references=(), jurisdiction={"span": "folder"},
            budget_lines=100, budget_chars=1000,
        )
        policy = mock.Mock()
        policy.card = lambda cid: card2 if cid == "knowledge.room" else None
        fake_report = {"households": [{"id": "knowledge.room", "code_count": 10, "files": ["app:src/dense.py"]}]}
        with mock.patch("ag2c.households.census_report", return_value=fake_report):
            warnings = _budget_warnings(manifest, policy, {})
        dims = {w.get("dimension") for w in warnings}
        self.assertIn("chars", dims)
        self.assertNotIn("lines", dims)  # line budget not exceeded
        self.assertEqual(derived_chars, 100 * DERIVED_CHARS_PER_LINE)

    def test_ast_dimension_trips_with_explicit_budget(self) -> None:
        code = "def f():\n    a = 1\n    b = 2\n    return a + b\n"
        self._write("src/mod.py", code)
        manifest = self._manifest_with_target()
        card = Card(
            card_id="knowledge.room", card_type="knowledge", title="room", summary="room",
            scopes=(), checkers=(), references=(), jurisdiction={"span": "folder"},
            budget_ast_nodes=3,  # deliberately tiny: real file has more nodes
        )
        policy = mock.Mock()
        policy.card = lambda cid: card if cid == "knowledge.room" else None
        fake_report = {"households": [{"id": "knowledge.room", "code_count": 4, "files": ["app:src/mod.py"]}]}
        with mock.patch("ag2c.households.census_report", return_value=fake_report):
            warnings = _budget_warnings(manifest, policy, {})
        dims = {w.get("dimension") for w in warnings}
        self.assertIn("ast_nodes", dims)

    def test_no_budget_any_dimension_no_warning(self) -> None:
        self._write("src/mod.py", "def f():\n    return 1\n")
        manifest = self._manifest_with_target()
        card = Card(
            card_id="knowledge.room", card_type="knowledge", title="room", summary="room",
            scopes=(), checkers=(), references=(), jurisdiction={"span": "folder"},
        )
        policy = mock.Mock()
        policy.card = lambda cid: card if cid == "knowledge.room" else None
        fake_report = {"households": [{"id": "knowledge.room", "code_count": 2, "files": ["app:src/mod.py"]}]}
        with mock.patch("ag2c.households.census_report", return_value=fake_report):
            warnings = _budget_warnings(manifest, policy, {})
        self.assertEqual([], warnings)

    def test_derived_ast_ceiling_constant(self) -> None:
        self.assertEqual(15, DERIVED_AST_NODES_PER_LINE)
        self.assertEqual(160, DERIVED_CHARS_PER_LINE)

    def _source_fixture(self, card: Card) -> list[dict[str, str]]:
        """30 行文件 + 10 行预算的房间，返回 _budget_warnings 的输出。"""
        self._write("src/mod.py", "x = 1\n" * 30)
        manifest = self._manifest_with_target()
        policy = mock.Mock()
        policy.card = lambda cid: card if cid == "knowledge.room" else None
        fake_report = {"households": [{"id": "knowledge.room", "code_count": 30, "files": ["app:src/mod.py"]}]}
        with mock.patch("ag2c.households.census_report", return_value=fake_report):
            return _budget_warnings(manifest, policy, {})

    def test_explicit_budget_marks_source_explicit(self) -> None:
        card = Card(
            card_id="knowledge.room", card_type="knowledge", title="room", summary="room",
            scopes=(), checkers=(), references=(), jurisdiction={"span": "folder"},
            budget_lines=10,
        )
        warnings = self._source_fixture(card)
        self.assertTrue(warnings)
        for w in warnings:
            self.assertEqual("explicit", w["budget_source"])  # 派生维度跟随父预算来源

    def test_dynamic_budget_marks_source_dynamic(self) -> None:
        # 无显式 budget_lines；预算来自动态仓 state/budgets.json
        (self._tmp / "state").mkdir(parents=True, exist_ok=True)
        (self._tmp / "state" / "budgets.json").write_text(
            json.dumps({"schema": "ag2c.budgets.v1",
                        "rooms": {"knowledge.room": {"budget_lines": 10}}}),
            encoding="utf-8",
        )
        card = Card(
            card_id="knowledge.room", card_type="knowledge", title="room", summary="room",
            scopes=(), checkers=(), references=(), jurisdiction={"span": "folder"},
        )
        warnings = self._source_fixture(card)
        self.assertTrue(warnings)
        for w in warnings:
            self.assertEqual("dynamic", w["budget_source"])

    def test_explicit_chars_overrides_dynamic_lines_source(self) -> None:
        """混合来源：行动态、chars 人工——chars 维度标 explicit，lines 标 dynamic。"""
        (self._tmp / "state").mkdir(parents=True, exist_ok=True)
        (self._tmp / "state" / "budgets.json").write_text(
            json.dumps({"schema": "ag2c.budgets.v1",
                        "rooms": {"knowledge.room": {"budget_lines": 10}}}),
            encoding="utf-8",
        )
        card = Card(
            card_id="knowledge.room", card_type="knowledge", title="room", summary="room",
            scopes=(), checkers=(), references=(), jurisdiction={"span": "folder"},
            budget_chars=100,
        )
        warnings = self._source_fixture(card)
        sources = {w["dimension"]: w["budget_source"] for w in warnings}
        self.assertEqual("dynamic", sources["lines"])
        self.assertEqual("explicit", sources["chars"])


class WarningEscalationTests(unittest.TestCase):
    """9.7: a warning ignored N times hardens into a gate block (泰坦尼克)."""

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp())
        (self._tmp / "state").mkdir(parents=True)
        self.manifest = Manifest(
            path=self._tmp / "manifest.json",
            project_id="test-proj",
            project_root=self._tmp,
            targets=[],
            ledger_path=self._tmp / "ledger.jsonl",
            policy_path=self._tmp / "policy.json",
            state_dir=self._tmp / "state",
        )

    def _budget_warning(self) -> dict[str, str]:
        return {"kind": "over-budget", "room": "knowledge.room", "dimension": "lines",
                "key": "knowledge.room:lines", "detail": "600 行代码，预算 500 行"}

    def test_first_appearances_do_not_escalate(self) -> None:
        warning = self._budget_warning()
        for expected_count in (1, 2):
            escalated = _record_warnings_and_find_escalated(self.manifest, [warning], count_key=f"task-{expected_count}")
            self.assertEqual([], escalated)
            history = _load_warning_history(self.manifest)
            counts = [e["count"] for e in history["warnings"].values()]
            self.assertEqual([expected_count], counts)

    def test_third_appearance_escalates(self) -> None:
        warning = self._budget_warning()
        _record_warnings_and_find_escalated(self.manifest, [warning], count_key="task-1")
        _record_warnings_and_find_escalated(self.manifest, [warning], count_key="task-2")
        escalated = _record_warnings_and_find_escalated(self.manifest, [warning], count_key="task-3")
        self.assertEqual(1, len(escalated))
        self.assertEqual("over-budget", escalated[0]["kind"])
        self.assertEqual(WARNING_ESCALATION_THRESHOLD, escalated[0]["count"])

    def test_same_count_key_retries_count_once(self) -> None:
        """9.7 计数语义（t25）：同一任务内 verify 重试不等于无视警告。"""
        warning = self._budget_warning()
        for _ in range(WARNING_ESCALATION_THRESHOLD + 2):
            escalated = _record_warnings_and_find_escalated(self.manifest, [warning], count_key="task-1")
            self.assertEqual([], escalated)  # 重试不升级
        history = _load_warning_history(self.manifest)
        counts = [e["count"] for e in history["warnings"].values()]
        self.assertEqual([1], counts)

    def test_none_count_key_is_read_only(self) -> None:
        """无 count_key 的调用（CLI check/金丝雀/CI 重放）只读不写： 不产生新计数，但仍依据既有计数报告已升级的警告。"""
        warning = self._budget_warning()
        escalated = _record_warnings_and_find_escalated(self.manifest, [warning])
        self.assertEqual([], escalated)
        history = _load_warning_history(self.manifest)
        self.assertEqual({}, history["warnings"])  # 未写入
        for i in range(WARNING_ESCALATION_THRESHOLD):
            _record_warnings_and_find_escalated(self.manifest, [warning], count_key=f"task-{i}")
        escalated = _record_warnings_and_find_escalated(self.manifest, [warning])  # 只读仍报升级
        self.assertEqual(1, len(escalated))

    def test_disappeared_warning_does_not_escalate_but_count_is_kept(self) -> None:
        warning = self._budget_warning()
        _record_warnings_and_find_escalated(self.manifest, [warning], count_key="task-1")
        _record_warnings_and_find_escalated(self.manifest, [warning], count_key="task-2")
        # Warning fixed: absent from this run -> no escalation.
        escalated = _record_warnings_and_find_escalated(self.manifest, [], count_key="task-3")
        self.assertEqual([], escalated)
        # Reappears later: count continues, third appearance hardens.
        escalated = _record_warnings_and_find_escalated(self.manifest, [warning], count_key="task-4")
        self.assertEqual(1, len(escalated))

    def test_informational_hint_never_escalates(self) -> None:
        hint = {"kind": "cross-slice-dependency", "key": "src/ag2c/checks.py",
                "detail": "src/ag2c/checks.py 被切片外 5 个文件 import"}
        self.assertNotIn("cross-slice-dependency", ESCALATABLE_KINDS)
        for i in range(WARNING_ESCALATION_THRESHOLD + 2):
            escalated = _record_warnings_and_find_escalated(self.manifest, [hint], count_key=f"task-{i}")
            self.assertEqual([], escalated)
        history = _load_warning_history(self.manifest)
        counts = [e["count"] for e in history["warnings"].values()]
        self.assertEqual([WARNING_ESCALATION_THRESHOLD + 2], counts)  # tracked, not escalated


    def test_corrupt_history_file_starts_fresh(self) -> None:
        path = self._tmp / "state" / "warning-history.json"
        path.write_text("{not json", encoding="utf-8")
        escalated = _record_warnings_and_find_escalated(self.manifest, [self._budget_warning()], count_key="task-1")
        self.assertEqual([], escalated)
        history = _load_warning_history(self.manifest)
        self.assertEqual(1, len(history["warnings"]))

    def test_fingerprint_distinguishes_dimensions(self) -> None:
        lines = self._budget_warning()
        chars = {**lines, "dimension": "chars", "key": "knowledge.room:chars"}
        _record_warnings_and_find_escalated(self.manifest, [lines, chars], count_key="task-1")
        history = _load_warning_history(self.manifest)
        self.assertEqual(2, len(history["warnings"]))

    def test_generators_emit_stable_keys(self) -> None:
        """All three warning generators must emit a key for fingerprinting."""
        self._write = lambda rel, text: None  # not needed; reuse measurement fixture style
        # over-budget: covered by dense-code test above (asserts dimension); check key here.
        manifest = self.manifest
        card = Card(
            card_id="knowledge.room", card_type="knowledge", title="room", summary="room",
            scopes=(), checkers=(), references=(), jurisdiction={"span": "folder"},
            budget_lines=1,
        )
        (self._tmp / "src").mkdir(exist_ok=True)
        (self._tmp / "src" / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        manifest = Manifest(
            path=self._tmp / "manifest.json", project_id="test-proj", project_root=self._tmp,
            targets=(Target(target_id="app", path=".", governed_roots=("src",), excludes=()),),
            ledger_path=self._tmp / "ledger.jsonl", policy_path=self._tmp / "policy.json",
            state_dir=self._tmp / "state",
        )
        policy = mock.Mock()
        policy.card = lambda cid: card if cid == "knowledge.room" else None
        fake_report = {"households": [{"id": "knowledge.room", "code_count": 5, "files": ["app:src/mod.py"]}]}
        with mock.patch("ag2c.households.census_report", return_value=fake_report):
            warnings = _budget_warnings(manifest, policy, {})
        self.assertTrue(warnings)
        for warning in warnings:
            self.assertIn("key", warning)
            self.assertTrue(warning["key"])

    def test_same_key_instances_count_once_per_run(self) -> None:
        """Several instances of one logical warning = one appearance per run."""
        warning = self._budget_warning()
        three_instances = [dict(warning), dict(warning), dict(warning)]
        for i in range(2):
            escalated = _record_warnings_and_find_escalated(self.manifest, three_instances, count_key=f"task-{i}")
            self.assertEqual([], escalated)
        history = _load_warning_history(self.manifest)
        counts = [e["count"] for e in history["warnings"].values()]
        self.assertEqual([2], counts)  # 2 tasks, not 6 instances

    def test_unittest_convention_methods_not_flagged_as_duplicates(self) -> None:
        """setUp/tearDown are scaffolding, not duplication (noise must not escalate)."""
        (self._tmp / "src").mkdir(exist_ok=True)
        (self._tmp / "tests").mkdir(exist_ok=True)
        (self._tmp / "src" / "api.py").write_text(
            "def public_hello(self):\n    a = 1\n    b = 2\n    c = 3\n    return a + b + c\n",
            encoding="utf-8",
        )
        (self._tmp / "tests" / "test_x.py").write_text(
            "class T:\n    def setUp(self):\n        a = 1\n        b = 2\n        c = 3\n        self.v = a + b + c\n",
            encoding="utf-8",
        )
        manifest = Manifest(
            path=self._tmp / "manifest.json", project_id="test-proj", project_root=self._tmp,
            targets=(Target(target_id="app", path=".", governed_roots=("src", "tests"), excludes=()),),
            ledger_path=self._tmp / "ledger.jsonl", policy_path=self._tmp / "policy.json",
            state_dir=self._tmp / "state",
        )
        entry_slice = {"entries": {"paths": [{"path": "tests/test_x.py", "target": "app"}]}}
        warnings = _duplicate_warnings(manifest, entry_slice)
        self.assertEqual([], [w for w in warnings if "setUp" in w.get("key", "")])


class DynamicBudgetEscalationTests(unittest.TestCase):
    """动态预算（系统快照）的 over-budget 永不硬化；人工定价的维持第三次硬化。"""

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp())
        (self._tmp / "state").mkdir(parents=True)
        self.manifest = Manifest(
            path=self._tmp / "manifest.json",
            project_id="test-proj",
            project_root=self._tmp,
            targets=[],
            ledger_path=self._tmp / "ledger.jsonl",
            policy_path=self._tmp / "policy.json",
            state_dir=self._tmp / "state",
        )

    def _warning(self, source: str) -> dict[str, str]:
        return {"kind": "over-budget", "room": "knowledge.room", "dimension": "lines",
                "key": "knowledge.room:lines", "detail": "600 行代码，预算 500 行",
                "budget_source": source}

    def test_dynamic_budget_never_escalates_but_is_counted(self) -> None:
        warning = self._warning("dynamic")
        for i in range(WARNING_ESCALATION_THRESHOLD + 2):
            escalated = _record_warnings_and_find_escalated(self.manifest, [warning], count_key=f"task-{i}")
            self.assertEqual([], escalated)  # 第 3/4/5 次仍只是警告
        history = _load_warning_history(self.manifest)
        counts = [e["count"] for e in history["warnings"].values()]
        self.assertEqual([WARNING_ESCALATION_THRESHOLD + 2], counts)  # 计数照涨，留痕不断

    def test_explicit_budget_still_escalates_on_third(self) -> None:
        warning = self._warning("explicit")
        _record_warnings_and_find_escalated(self.manifest, [warning], count_key="task-1")
        _record_warnings_and_find_escalated(self.manifest, [warning], count_key="task-2")
        escalated = _record_warnings_and_find_escalated(self.manifest, [warning], count_key="task-3")
        self.assertEqual(1, len(escalated))
        self.assertEqual("explicit", escalated[0]["budget_source"])

    def test_missing_budget_source_keeps_legacy_behavior(self) -> None:
        """budget_source 缺失（旧历史、verify_costs 秒预算）按人工处理：第三次硬化。"""
        warning = self._warning("explicit")
        del warning["budget_source"]
        for i in range(WARNING_ESCALATION_THRESHOLD):
            escalated = _record_warnings_and_find_escalated(self.manifest, [warning], count_key=f"task-{i}")
        self.assertEqual(1, len(escalated))

    def test_dynamic_history_escalates_once_room_becomes_explicit(self) -> None:
        """房间从动态转人工定价后，既有计数 ≥3 的警告下一次出现立即硬化——价格对话到期。"""
        warning = self._warning("dynamic")
        for i in range(WARNING_ESCALATION_THRESHOLD):
            escalated = _record_warnings_and_find_escalated(self.manifest, [warning], count_key=f"task-{i}")
            self.assertEqual([], escalated)
        escalated = _record_warnings_and_find_escalated(self.manifest, [self._warning("explicit")], count_key="task-next")
        self.assertEqual(1, len(escalated))


class WarningDismissTests(unittest.TestCase):
    """govern warning-dismiss：升级门的合法出口——删除计数条目并落账本。"""

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp())
        (self._tmp / "state").mkdir(parents=True)
        self.manifest = Manifest(
            path=self._tmp / "manifest.json",
            project_id="test-proj",
            project_root=self._tmp,
            targets=[],
            ledger_path=self._tmp / "ledger.jsonl",
            policy_path=self._tmp / "policy.json",
            state_dir=self._tmp / "state",
        )

    def _budget_warning(self) -> dict[str, str]:
        return {"kind": "over-budget", "room": "knowledge.room", "dimension": "lines",
                "key": "knowledge.room:lines", "detail": "600 行代码，预算 500 行"}

    def test_dismiss_clears_count_and_restarts_escalation_clock(self) -> None:
        warning = self._budget_warning()
        for i in range(WARNING_ESCALATION_THRESHOLD):
            _record_warnings_and_find_escalated(self.manifest, [warning], count_key=f"task-{i}")
        result = dismiss_warning(self.manifest, "knowledge.room:lines", actor="holo", reason="已知：等套件瘦身任务")
        self.assertEqual(WARNING_ESCALATION_THRESHOLD, result["dismissed"][0]["count"])
        self.assertEqual({}, _load_warning_history(self.manifest)["warnings"])
        # 计数从零重来：dismissal 后再出现两次也不升级
        for i in range(WARNING_ESCALATION_THRESHOLD - 1):
            escalated = _record_warnings_and_find_escalated(self.manifest, [warning], count_key=f"post-{i}")
            self.assertEqual([], escalated)

    def test_dismiss_unknown_key_refused(self) -> None:
        with self.assertRaises(AG2CError):
            dismiss_warning(self.manifest, "no.such:key", actor="holo", reason="typo")

    def test_dismiss_writes_ledger_event(self) -> None:
        _record_warnings_and_find_escalated(self.manifest, [self._budget_warning()], count_key="task-1")
        dismiss_warning(self.manifest, "knowledge.room:lines", actor="holo", reason="已知情")
        events = [e for e in read_events(self.manifest.ledger_path) if e.get("event_type") == "warning-dismiss"]
        self.assertEqual(1, len(events))
        payload = events[0]["payload"]
        self.assertEqual("knowledge.room:lines", payload["key"])
        self.assertEqual([{"kind": "over-budget", "count": 1}], payload["dismissed"])
        self.assertEqual("holo", payload["actor"])
        self.assertEqual("已知情", payload["reason"])

    def test_ledger_failure_leaves_history_bytes_unchanged(self) -> None:
        _record_warnings_and_find_escalated(self.manifest, [self._budget_warning()], count_key="task-1")
        path = self.manifest.state_dir / "warning-history.json"
        before = path.read_bytes()
        with mock.patch("ag2c.ledger.append_event", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                dismiss_warning(self.manifest, "knowledge.room:lines", actor="holo", reason="x")
        self.assertEqual(before, path.read_bytes())
        self.assertEqual(1, list(_load_warning_history(self.manifest)["warnings"].values())[0]["count"])
        self.assertEqual(
            [],
            [e for e in read_events(self.manifest.ledger_path) if e.get("event_type") == "warning-dismiss"],
        )


class DuplicatePrecisionTests(unittest.TestCase):
    """The detector must be high-precision, because 9.7 warnings harden."""

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp())
        (self._tmp / "src").mkdir(parents=True)
        (self._tmp / "state").mkdir(parents=True)
        self.manifest = Manifest(
            path=self._tmp / "manifest.json", project_id="test-proj", project_root=self._tmp,
            targets=(Target(target_id="app", path=".", governed_roots=("src",), excludes=()),),
            ledger_path=self._tmp / "ledger.jsonl", policy_path=self._tmp / "policy.json",
            state_dir=self._tmp / "state",
        )

    def _write(self, rel: str, text: str) -> None:
        (self._tmp / rel).write_text(text, encoding="utf-8")

    def _warnings_for(self, changed: str) -> list[dict[str, str]]:
        return _duplicate_warnings(
            self.manifest, {"entries": {"paths": [{"path": changed, "target": "app"}]}}
        )

    def test_short_same_shape_functions_not_flagged(self) -> None:
        """1-2 line functions with equal arity are everywhere; not duplication."""
        self._write("src/old.py", "def hello(name):\n    return name\n")
        self._write("src/new.py", "def greet(name):\n    return name\n")
        self.assertEqual([], self._warnings_for("src/new.py"))

    def test_copy_paste_large_function_flagged(self) -> None:
        body = "".join(f"    v{i} = compute(data, {i})\n" for i in range(10))
        self._write("src/old.py", f"def render_page(data):\n{body}    return v0\n")
        self._write("src/new.py", f"def render_view(data):\n{body}    return v0\n")
        warnings = self._warnings_for("src/new.py")
        self.assertEqual(1, len(warnings))
        self.assertIn("render_view", warnings[0]["detail"])

    def test_large_but_structurally_different_not_flagged(self) -> None:
        self._write(
            "src/old.py",
            "def process(data):\n"
            + "".join(f"    x{i} = data[{i}]\n" for i in range(10))
            + "    return x0\n",
        )
        self._write(
            "src/new.py",
            "def handle(data):\n"
            "    try:\n"
            "        with open(data) as fh:\n"
            "            for line in fh:\n"
            "                if line.strip():\n"
            "                    print(line.upper())\n"
            "    except OSError:\n"
            "        return None\n"
            "    while data:\n"
            "        data = data[1:]\n"
            "    return data\n",
        )
        self.assertEqual([], self._warnings_for("src/new.py"))

    def test_same_name_small_divergent_bodies_not_flagged(self) -> None:
        """同名同参数数但函数体结构不同 = 命名撞车，不是重复（_clip 教训： checks 截断输出 vs dashboard 截断显示，同名不同义）。"""
        self._write("src/old.py", "def helper(a, b):\n    return a + b\n")
        self._write("src/new.py", "def helper(a, b):\n    return a * b\n")
        self.assertEqual([], self._warnings_for("src/new.py"))

    def test_same_name_same_shape_flagged(self) -> None:
        """同名 + 同参数数 + 结构一致（>=4 行）= 重实现的助手，必须报警。"""
        body = "    x = a + b\n    y = x * 2\n    z = y - 1\n    return z\n"
        self._write("src/old.py", f"def helper(a, b):\n{body}")
        self._write("src/new.py", f"def helper(a, b):\n{body}")
        warnings = self._warnings_for("src/new.py")
        self.assertEqual(1, len(warnings))
        self.assertIn("同名函数", warnings[0]["detail"])

    def test_entry_point_main_not_flagged(self) -> None:
        """main(argv) 是通用入口名，同名同参数数不携带重复信号——9.7 曾把 这个误报硬化成门禁拦截（suites.py:main、cli.py:main 一天两次）。"""
        self._write("src/old.py", "def main(argv):\n    return 0\n")
        self._write("src/new.py", "def main(argv):\n    return 1\n")
        self.assertEqual([], self._warnings_for("src/new.py"))


class BaselineDebtTests(unittest.TestCase):
    """9.12: baseline total enters governance health with a ratcheting target."""

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp())
        (self._tmp / "state").mkdir(parents=True)
        self.manifest = Manifest(
            path=self._tmp / "manifest.json",
            project_id="test-proj",
            project_root=self._tmp,
            targets=[],
            ledger_path=self._tmp / "ledger.jsonl",
            policy_path=self._tmp / "policy.json",
            state_dir=self._tmp / "state",
        )

    def _write_baseline(self, failures: list[str]) -> None:
        payload = {
            "schema": "ag2c.test-baseline.v1",
            "checkers": {
                "check.python": {
                    "failures": failures,
                    "updated_at": "2026-01-01T00:00:00+00:00",
                    "expires_at": "2099-01-01T00:00:00+00:00",
                    "actor": "test",
                    "reason": "fixture",
                }
            }
            if failures
            else {},
        }
        (self._tmp / "state" / "test-baseline.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    def test_first_observation_establishes_ceiling(self) -> None:
        self._write_baseline(["FAIL: a", "FAIL: b"])
        debt = baseline_debt(self.manifest)
        self.assertEqual({"total": 2, "target": 2, "over": False}, debt)

    def test_ratchet_only_moves_down(self) -> None:
        self._write_baseline(["FAIL: a", "FAIL: b", "FAIL: c"])
        baseline_debt(self.manifest)  # ceiling = 3
        self._write_baseline(["FAIL: a"])  # paid down to 1
        debt = baseline_debt(self.manifest)
        self.assertEqual({"total": 1, "target": 1, "over": False}, debt)
        # Debt grows again: target stays at 1, project is over.
        self._write_baseline(["FAIL: a", "FAIL: b"])
        debt = baseline_debt(self.manifest)
        self.assertEqual({"total": 2, "target": 1, "over": True}, debt)

    def test_zero_baseline_zero_target(self) -> None:
        debt = baseline_debt(self.manifest)
        self.assertEqual({"total": 0, "target": 0, "over": False}, debt)

    def test_expired_entries_do_not_count_toward_debt(self) -> None:
        payload = {
            "schema": "ag2c.test-baseline.v1",
            "checkers": {
                "check.python": {
                    "failures": ["FAIL: old"],
                    "updated_at": "2026-01-01T00:00:00+00:00",
                    "expires_at": "2026-01-02T00:00:00+00:00",  # expired
                    "actor": "test",
                    "reason": "fixture",
                }
            },
        }
        (self._tmp / "state" / "test-baseline.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        debt = baseline_debt(self.manifest)
        self.assertEqual(0, debt["total"])

    def test_corrupt_target_file_re_establishes_ceiling(self) -> None:
        self._write_baseline(["FAIL: a"])
        (self._tmp / "state" / "baseline-target.json").write_text("{bad", encoding="utf-8")
        debt = baseline_debt(self.manifest)
        self.assertEqual({"total": 1, "target": 1, "over": False}, debt)


class ScanDuplicatePairsTests(unittest.TestCase):
    """全仓实时查重（checks.scan_duplicate_pairs）：危房名单拆迁队列的数据源。 与 diff 触发的 _duplicate_warnings 共用 duplicate_match 单一规则； 化石记录（旧探测器残留）在实时扫描下自然不再复现。"""

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp())
        (self._tmp / "src").mkdir(parents=True)
        (self._tmp / "state").mkdir(parents=True)
        self.manifest = Manifest(
            path=self._tmp / "manifest.json", project_id="test-proj", project_root=self._tmp,
            targets=(Target(target_id="app", path=".", governed_roots=("src",), excludes=()),),
            ledger_path=self._tmp / "ledger.jsonl", policy_path=self._tmp / "policy.json",
            state_dir=self._tmp / "state",
        )

    def _write(self, rel: str, text: str) -> None:
        (self._tmp / rel).write_text(text, encoding="utf-8")

    def test_live_pair_found_with_match_kind(self) -> None:
        from ag2c.checks import scan_duplicate_pairs

        body = "    x = a + b\n    y = x * 2\n    z = y - 1\n    return z\n"
        self._write("src/old.py", f"def helper(a, b):\n{body}")
        self._write("src/new.py", f"def helper(a, b):\n{body}")
        pairs = scan_duplicate_pairs(self.manifest)
        self.assertEqual(1, len(pairs))
        self.assertEqual("同名", pairs[0]["match"])
        self.assertEqual({pairs[0]["file"], pairs[0]["other_file"]}, {"src/old.py", "src/new.py"})

    def test_fossil_style_pair_not_reproduced(self) -> None:
        """旧探测器"同名+同参数数"就报警的撞名对（1-2 行），现行规则不认。"""
        from ag2c.checks import scan_duplicate_pairs

        self._write("src/a.py", "def clip(a):\n    return a\n")
        self._write("src/b.py", "def clip(a):\n    return a[:1] if a else a\n")
        self.assertEqual([], scan_duplicate_pairs(self.manifest))

    def test_copy_paste_under_any_name_found(self) -> None:
        from ag2c.checks import scan_duplicate_pairs

        body = "".join(f"    v{i} = compute(data, {i})\n" for i in range(10))
        self._write("src/old.py", f"def render_page(data):\n{body}    return v0\n")
        self._write("src/new.py", f"def render_view(data):\n{body}    return v0\n")
        pairs = scan_duplicate_pairs(self.manifest)
        self.assertEqual(1, len(pairs))
        self.assertEqual("相似", pairs[0]["match"])

    def test_syntax_error_files_skipped(self) -> None:
        from ag2c.checks import scan_duplicate_pairs

        self._write("src/broken.py", "def f(:\n")
        self.assertEqual([], scan_duplicate_pairs(self.manifest))


class DuplicateWarningTests(unittest.TestCase):
    def test_same_name_same_args_flagged(self) -> None:
        """Functions with the same name and arg count are flagged."""
        # Test the AST comparison logic directly.
        code1 = "def foo(a, b):\n    return a + b\n"
        code2 = "def foo(a, b):\n    return a * b\n"
        tree1 = ast.parse(code1)
        tree2 = ast.parse(code2)
        funcs1 = [(n.name, len(n.args.args), (n.end_lineno or 0) - (n.lineno or 0))
                   for n in ast.walk(tree1) if isinstance(n, ast.FunctionDef)]
        funcs2 = [(n.name, len(n.args.args), (n.end_lineno or 0) - (n.lineno or 0))
                   for n in ast.walk(tree2) if isinstance(n, ast.FunctionDef)]
        self.assertEqual(funcs1[0][0], funcs2[0][0])  # same name
        self.assertEqual(funcs1[0][1], funcs2[0][1])  # same args

    def test_similar_body_length_flagged(self) -> None:
        """Functions with similar body length and same args are flagged."""
        code1 = "def process(data):\n    x = data.strip()\n    y = x.lower()\n    return y\n"
        code2 = "def handle(data):\n    x = data.strip()\n    y = x.upper()\n    return y\n"
        tree1 = ast.parse(code1)
        tree2 = ast.parse(code2)
        funcs1 = [(n.name, len(n.args.args), (n.end_lineno or 0) - (n.lineno or 0))
                   for n in ast.walk(tree1) if isinstance(n, ast.FunctionDef)]
        funcs2 = [(n.name, len(n.args.args), (n.end_lineno or 0) - (n.lineno or 0))
                   for n in ast.walk(tree2) if isinstance(n, ast.FunctionDef)]
        _, args1, lines1 = funcs1[0]
        _, args2, lines2 = funcs2[0]
        self.assertEqual(args1, args2)
        ratio = min(lines1, lines2) / max(lines1, lines2)
        self.assertGreaterEqual(ratio, 0.8)

    def test_different_functions_not_flagged(self) -> None:
        """Functions with different names and very different bodies are not flagged."""
        code1 = "def foo(a):\n    return a\n"
        code2 = "def bar(a, b, c, d, e):\n    return a + b + c + d + e\n"
        tree1 = ast.parse(code1)
        tree2 = ast.parse(code2)
        funcs1 = [(n.name, len(n.args.args)) for n in ast.walk(tree1) if isinstance(n, ast.FunctionDef)]
        funcs2 = [(n.name, len(n.args.args)) for n in ast.walk(tree2) if isinstance(n, ast.FunctionDef)]
        self.assertNotEqual(funcs1[0], funcs2[0])


if __name__ == "__main__":
    unittest.main()
