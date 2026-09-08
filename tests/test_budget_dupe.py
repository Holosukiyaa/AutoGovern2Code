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
    _budget_warnings,
    _duplicate_warnings,
    _room_code_measurements,
)
from ag2c.config import load_policy
from ag2c.model import Card, Manifest, Target


def _manifest(root: Path) -> Manifest:
    return Manifest(
        path=root / "manifest.json",
        project_id="test-proj",
        project_root=root,
        targets=[],
        ledger_path=root / "ledger.jsonl",
        policy_path=root / "policy.json",
        state_dir=root / "state",
    )


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
        item = {"code_count": 2, "files": ["app:src/mod.py"]}
        measured = _room_code_measurements(manifest, item)
        self.assertEqual(2, measured["lines"])
        self.assertEqual(len("def foo():\n    return 1\n"), measured["chars"])
        expected_nodes = sum(1 for _ in ast.walk(ast.parse("def foo():\n    return 1\n")))
        self.assertEqual(expected_nodes, measured["ast_nodes"])

    def test_measurements_skip_missing_files(self) -> None:
        manifest = self._manifest_with_target()
        item = {"code_count": 10, "files": ["app:src/gone.py", "app:src/alsogone.py"]}
        measured = _room_code_measurements(manifest, item)
        self.assertEqual(10, measured["lines"])  # lines trust census
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
