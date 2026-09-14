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
from ag2c.errors import AG2CError
from ag2c.flatten import flatten_queue, flatten_split, pure_move_violations


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

    def test_split_copies_defs_and_reexports(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = git_project(Path(directory) / "demo")
            pkg = root / "src" / "ag2c"
            pkg.mkdir(parents=True)
            (pkg / "__init__.py").write_text("", encoding="utf-8")
            (pkg / "mod.py").write_text(
                "from __future__ import annotations\n\n"
                "def foo():\n    return 1\n\n"
                "def bar():\n    return 2\n\n"
                "def keep():\n    return 3\n",
                encoding="utf-8",
            )
            _git(root, "add", "--all"); _git(root, "commit", "-m", "mod")
            dry = flatten_split(root, source="src/ag2c/mod.py", dest="src/ag2c/piece.py", names=["foo", "bar"], dry_run=True)
            self.assertTrue(dry["dry_run"]); self.assertFalse((pkg / "piece.py").exists())
            flatten_split(root, source="src/ag2c/mod.py", dest="src/ag2c/piece.py", names=["foo", "bar"])
            dest = (pkg / "piece.py").read_text(encoding="utf-8")
            src = (pkg / "mod.py").read_text(encoding="utf-8")
            self.assertIn("def foo():", dest); self.assertIn("return 1", dest)
            self.assertIn("from .piece import foo, bar", src); self.assertIn("def keep():", src)
            self.assertNotIn("def foo():", src)
            _git(root, "add", "--all")
            diff = _git(root, "diff", "--cached", "--no-ext-diff", "--no-color")
            self.assertEqual([], pure_move_violations(diff))
            with self.assertRaises(AG2CError) as raised:
                flatten_split(root, source="src/ag2c/mod.py", dest="src/ag2c/other.py", names=["missing"])
            self.assertIn("missing", str(raised.exception))
            (pkg / "inner.py").write_text(
                '"""mod doc"""\n@dec\ndef foo():\n    return 1\n\ndef keep():\n    from x import y\n    return 2\n',
                encoding="utf-8",
            )
            flatten_split(root, source="src/ag2c/inner.py", dest="src/ag2c/slice.py", names=["foo"])
            inner = (pkg / "inner.py").read_text(encoding="utf-8")
            self.assertTrue(inner.startswith('"""mod doc"""'))
            self.assertIn("from .slice import foo", inner.split('"""mod doc"""', 1)[-1])
            self.assertIn("@dec", (pkg / "slice.py").read_text(encoding="utf-8"))
            self.assertNotIn("@dec", inner)
            self.assertIn("    from x import y", inner)
        fake = {"schema": "ag2c.flatten-split.v1", "source": "src/ag2c/mod.py", "dest": "src/ag2c/unused.py", "names": ["keep"], "dry_run": True, "ranges": []}
        out = io.StringIO()
        with patch("ag2c.flatten.flatten_split", return_value=fake), patch("sys.stdout", out):
            self.assertEqual(0, main(["govern", "flatten-split", "--source", "src/ag2c/mod.py", "--dest", "src/ag2c/unused.py", "--name", "keep", "--dry-run"]))
        payload = json.loads(out.getvalue())
        self.assertEqual(["keep"], payload["names"]); self.assertTrue(payload["dry_run"])

    def test_queue_under_foreign_tree_without_src_ag2c(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = git_project(Path(directory) / "demo")
            pkg = root / "src" / "app"
            pkg.mkdir(parents=True)
            (pkg / "thin.py").write_text("x = 1\n" * 10, encoding="utf-8")
            (pkg / "fat.py").write_text("x = 1\n" * 900, encoding="utf-8")
            _git(root, "add", "--all")
            _git(root, "commit", "-m", "add")
            (pkg / "fat.py").write_text("x = 1\n" * 900 + "# heat\n", encoding="utf-8")
            _git(root, "add", "--all")
            _git(root, "commit", "-m", "touch")
            self.assertEqual([], flatten_queue(root))
            self.assertEqual([], flatten_queue(root, under="src/missing"))
            items = flatten_queue(root, under="src/app")
            paths = [item["path"] for item in items]
            self.assertLess(paths.index("src/app/fat.py"), paths.index("src/app/thin.py"))

    def test_cli_flatten_queue_under(self) -> None:
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            self.assertEqual(0, main(["govern", "flatten-queue", "--under", "tests", "--format", "json"]))
        payload = json.loads(buf.getvalue())
        self.assertTrue(payload["items"])
        self.assertTrue(all(str(item["path"]).startswith("tests/") for item in payload["items"]))
        self.assertFalse(any(str(item["path"]).startswith("src/ag2c/") for item in payload["items"]))
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            self.assertEqual(0, main(["govern", "flatten-queue", "--under", "src/missing-nope", "--format", "json"]))
        self.assertEqual([], json.loads(buf.getvalue())["items"])
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            self.assertEqual(0, main(["govern", "flatten-queue", "--format", "json"]))
        default_items = json.loads(buf.getvalue())["items"]
        self.assertTrue(default_items)
        self.assertTrue(all(str(item["path"]).startswith("src/ag2c/") for item in default_items))
