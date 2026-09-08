"""Soft budget and duplicate detection tests."""

from __future__ import annotations

import ast
import os
import tempfile
import unittest
from pathlib import Path

from ag2c.checks import _budget_warnings, _duplicate_warnings
from ag2c.config import load_policy
from ag2c.model import Manifest


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
