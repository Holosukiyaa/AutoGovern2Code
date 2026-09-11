"""反向开发：flatten-queue 与纯搬运门。"""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bootstrap  # noqa: F401
from support import _git, git_project
from ag2c.cli import main
from ag2c.flatten import flatten_queue, pure_move_violations


def _diff(old: str, new: str, path: str = "src/ag2c/mod.py") -> str:
    rows = ["--- a/" + path, "+++ b/" + path, "@@"]
    rows += ["-" + line for line in old.splitlines()] + ["+" + line for line in new.splitlines()]
    return "\n".join(rows) + "\n"

class FlattenTests(unittest.TestCase):
    def test_gate_queue_and_cli(self) -> None:
        body = "def f():\n    return 1"
        self.assertEqual([], pure_move_violations(_diff(body, body)))
        self.assertEqual([], pure_move_violations(""))
        hits = pure_move_violations(_diff(body, "def f():\n    return 2"))
        self.assertEqual(1, len(hits)); self.assertIn("return 2", hits[0])
        added = "--- /dev/null\n+++ b/src/ag2c/new.py\n@@\n" + '+"""module doc"""\n+from x import y\n+def f():\n+    return 1\n'
        v = pure_move_violations(added)
        self.assertTrue(any("return 1" in i or "def f" in i for i in v))
        self.assertFalse(any("from x import y" in i or "module doc" in i for i in v))
        with tempfile.TemporaryDirectory() as directory:
            root = git_project(Path(directory) / "demo")
            pkg = root / "src" / "ag2c"; pkg.mkdir(parents=True)
            (pkg / "__init__.py").write_text("", encoding="utf-8")
            (pkg / "thin.py").write_text("x = 1\n" * 10, encoding="utf-8")
            (pkg / "fat.py").write_text("x = 1\n" * 900, encoding="utf-8")
            _git(root, "add", "--all"); _git(root, "commit", "-m", "add")
            (pkg / "fat.py").write_text("x = 1\n" * 900 + "# heat\n", encoding="utf-8")
            _git(root, "add", "--all"); _git(root, "commit", "-m", "touch")
            items = flatten_queue(root)
            paths = [item["path"] for item in items]
            self.assertLess(paths.index("src/ag2c/fat.py"), paths.index("src/ag2c/thin.py"))
            fat = next(item for item in items if item["path"] == "src/ag2c/fat.py"); thin = next(item for item in items if item["path"] == "src/ag2c/thin.py")
            self.assertGreater(fat["heat"], thin["heat"]); self.assertGreater(fat["score"], thin["score"])
        buf = io.StringIO()
        with patch("sys.stdin", io.StringIO(_diff(body, body))), patch("sys.stdout", buf):
            self.assertEqual(0, main(["govern", "flatten-check"]))
        self.assertEqual([], json.loads(buf.getvalue())["violations"])
