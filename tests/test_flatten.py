"""反向开发：flatten-queue 与纯搬运门。"""
from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bootstrap  # noqa: F401
from support import _git, git_project
from ag2c.cli_main import main
from ag2c.errors import AG2CError
from ag2c.flatten import flatten_bill, flatten_cut, flatten_door, flatten_glue, flatten_queue, flatten_split, pure_move_violations


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

    def test_bill_classifies_move_exam_and_behavior(self) -> None:
        empty = flatten_bill("")
        self.assertEqual([], empty["moves"])
        self.assertEqual([], empty["exams"])
        self.assertEqual([], empty["retarget"])
        self.assertEqual([], empty["behavior"])
        moved = (
            "--- a/src/ag2c/mod.py\n+++ b/src/ag2c/mod.py\n@@\n"
            "-def foo():\n-    return 1\n"
            "--- /dev/null\n+++ b/src/ag2c/piece.py\n@@\n"
            "+def foo():\n+    return 1\n"
        )
        bill = flatten_bill(moved)
        self.assertIn("src/ag2c/piece.py", bill["moves"])
        self.assertEqual([], bill["exams"])
        self.assertEqual([], bill["behavior"])
        exam = "--- /dev/null\n+++ b/tests/test_foo.py\n@@\n+def test_ok():\n+    assert True\n"
        exam_bill = flatten_bill(exam)
        self.assertEqual(["tests/test_foo.py"], exam_bill["exams"])
        self.assertEqual([], exam_bill["behavior"])
        pack_exam = "--- /dev/null\n+++ b/pack/exams/smoke/test_ok.py\n@@\n+def test_ok():\n+    assert True\n"
        pack_bill = flatten_bill(pack_exam)
        self.assertEqual(["pack/exams/smoke/test_ok.py"], pack_bill["exams"])
        self.assertEqual([], pack_bill["behavior"])
        logic = flatten_bill(_diff("def f():\n    return 1", "def f():\n    return 2"))
        self.assertTrue(logic["behavior"])
        self.assertEqual("src/ag2c/mod.py", logic["behavior"][0]["path"])
        self.assertEqual("ag2c.flatten-bill.v1", logic["schema"])
        buf = io.StringIO()
        with patch("sys.stdin", io.StringIO(moved)), patch("sys.stdout", buf):
            self.assertEqual(0, main(["govern", "flatten-bill", "--format", "json"]))
        payload = json.loads(buf.getvalue())
        self.assertIn("src/ag2c/piece.py", payload["moves"])
        self.assertEqual([], payload["behavior"])
        text_buf = io.StringIO()
        with patch("sys.stdin", io.StringIO(moved)), patch("sys.stdout", text_buf):
            self.assertEqual(0, main(["govern", "flatten-bill", "--format", "text"]))
        self.assertIn("搬家", text_buf.getvalue())
        self.assertIn("改路牌", text_buf.getvalue())
        retarget_diff = (
            "--- a/shop.py\n+++ b/shop.py\n@@\n"
            "-from .shop import bar\n"
            "+from .side import bar\n"
        )
        retarget_bill = flatten_bill(retarget_diff)
        self.assertEqual(["shop.py"], retarget_bill["retarget"])
        self.assertEqual([], retarget_bill["behavior"])
        self.assertEqual([], retarget_bill["moves"])
        buf = io.StringIO()
        with patch("sys.stdin", io.StringIO(retarget_diff)), patch("sys.stdout", buf):
            self.assertEqual(0, main(["govern", "flatten-bill", "--format", "json"]))
        self.assertEqual(["shop.py"], json.loads(buf.getvalue())["retarget"])
        text_buf = io.StringIO()
        with patch("sys.stdin", io.StringIO(retarget_diff)), patch("sys.stdout", text_buf):
            self.assertEqual(0, main(["govern", "flatten-bill", "--format", "text"]))
        retarget_text = text_buf.getvalue()
        self.assertIn("改路牌:", retarget_text)
        self.assertIn("  shop.py", retarget_text)
        self.assertIn("行为改动:\n  （无）", retarget_text)

    def test_glue_and_door_four_shops(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            glue = root / "glue"
            glue.mkdir()
            (glue / "shop.py").write_text("def foo():\n    return '计价'\n\nfrom .side import bar\n", encoding="utf-8")
            (glue / "side.py").write_text("def bar():\n    return '发货'\n", encoding="utf-8")
            (glue / "alice.py").write_text("from .shop import foo\n\ndef run():\n    return foo()\n", encoding="utf-8")
            (glue / "bob.py").write_text("from .shop import bar\n\ndef run():\n    return bar()\n", encoding="utf-8")
            report = flatten_glue(glue, "shop.py")
            self.assertTrue(report["glue"])
            self.assertTrue(any("转口" in item for item in report["reasons"]))
            self.assertTrue(any("两拨" in item for item in report["reasons"]))

            not_glue = root / "not_glue"
            not_glue.mkdir()
            (not_glue / "parser.py").write_text("def parse(text):\n    return text.strip()\n\ndef format(data):\n    return str(data)\n", encoding="utf-8")
            (not_glue / "app.py").write_text("from .parser import parse, format\n\ndef run(text):\n    return format(parse(text))\n", encoding="utf-8")
            clean = flatten_glue(not_glue, "parser.py")
            self.assertFalse(clean["glue"])

            init = root / "pkg"
            init.mkdir()
            (init / "__init__.py").write_text("from .side import bar\n", encoding="utf-8")
            (init / "side.py").write_text("def bar():\n    return 1\n", encoding="utf-8")
            (init / "bob.py").write_text("from . import bar\n", encoding="utf-8")
            self.assertFalse(flatten_glue(init, "__init__.py")["glue"])

            moved = root / "moved"
            moved.mkdir()
            (moved / "shop.py").write_text("def foo():\n    return '计价'\n\nfrom .side import bar\n", encoding="utf-8")
            (moved / "side.py").write_text("def bar():\n    return '发货'\n", encoding="utf-8")
            (moved / "alice.py").write_text("from .shop import foo\n\ndef run():\n    return foo()\n", encoding="utf-8")
            (moved / "bob.py").write_text("from .shop import bar\n\ndef run():\n    return bar()\n", encoding="utf-8")
            self.assertTrue(flatten_glue(moved, "shop.py")["glue"])
            door_moved = flatten_door(moved, old="shop.py", side="side.py", names=["bar"])
            self.assertFalse(door_moved["cut"])
            self.assertIn("转口", door_moved["reason"])

            cut = root / "cut"
            cut.mkdir()
            (cut / "shop.py").write_text("def foo():\n    return '计价'\n", encoding="utf-8")
            (cut / "side.py").write_text("def bar():\n    return '发货'\n", encoding="utf-8")
            (cut / "alice.py").write_text("from .shop import foo\n\ndef run():\n    return foo()\n", encoding="utf-8")
            (cut / "bob.py").write_text("from .side import bar\n\ndef run():\n    return bar()\n", encoding="utf-8")
            self.assertFalse(flatten_glue(cut, "shop.py")["glue"])
            door_cut = flatten_door(cut, old="shop.py", side="side.py", names=["bar"])
            self.assertTrue(door_cut["cut"])

            missing = flatten_glue
            with self.assertRaises(AG2CError):
                missing(root, "nope.py")
            with self.assertRaises(AG2CError):
                flatten_door(cut, old="shop.py", side="side.py", names=[])

        help_buf = io.StringIO()
        with patch("sys.stdout", help_buf):
            try:
                main(["govern", "flatten-glue", "--help"])
            except SystemExit as exc:
                self.assertEqual(0, exc.code)
        self.assertIn("flatten-glue", help_buf.getvalue())
        help_buf = io.StringIO()
        with patch("sys.stdout", help_buf):
            try:
                main(["govern", "flatten-door", "--help"])
            except SystemExit as exc:
                self.assertEqual(0, exc.code)
        self.assertIn("flatten-door", help_buf.getvalue())

        glue_root = Path(tempfile.mkdtemp())
        (glue_root / "shop.py").write_text("def foo():\n    return 1\n\nfrom .side import bar\n", encoding="utf-8")
        (glue_root / "side.py").write_text("def bar():\n    return 2\n", encoding="utf-8")
        (glue_root / "alice.py").write_text("from .shop import foo\n", encoding="utf-8")
        (glue_root / "bob.py").write_text("from .shop import bar\n", encoding="utf-8")
        here = Path.cwd()
        os.chdir(glue_root)
        try:
            buf = io.StringIO()
            err = io.StringIO()
            with patch("sys.stdout", buf), patch("sys.stderr", err):
                code = main(["govern", "flatten-glue", "--file", "shop.py", "--format", "json"])
            self.assertEqual(0, code, err.getvalue())
            self.assertTrue(json.loads(buf.getvalue())["glue"])
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                code = main(["govern", "flatten-door", "--old", "shop.py", "--side", "side.py", "--name", "bar", "--format", "json"])
            self.assertEqual(0, code)
            self.assertFalse(json.loads(buf.getvalue())["cut"])
            err = io.StringIO()
            with patch("sys.stderr", err):
                code = main(["govern", "flatten-glue", "--file", "missing.py", "--format", "json"])
            self.assertNotEqual(0, code)
            self.assertIn("flatten-glue missing file", err.getvalue())
        finally:
            os.chdir(here)

    def test_flatten_cut_dry_run_and_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "shop.py").write_text("def foo():\n    return 1\n\nfrom .side import bar\n", encoding="utf-8")
            (root / "side.py").write_text("def bar():\n    return 2\n", encoding="utf-8")
            (root / "alice.py").write_text("from .shop import foo\n", encoding="utf-8")
            (root / "bob.py").write_text("from .shop import bar\n", encoding="utf-8")
            (root / "mixed.py").write_text("from .shop import foo, bar\n", encoding="utf-8")
            (root / "nested.py").write_text("def run():\n    from .shop import bar\n    return bar()\n", encoding="utf-8")
            preview = flatten_cut(root, old="shop.py", side="side.py", names=["bar"], write=False)
            self.assertFalse(preview["write"])
            self.assertFalse(preview["cut"])
            self.assertIn("from .side import bar", (root / "shop.py").read_text(encoding="utf-8"))
            self.assertIn("from .shop import bar", (root / "bob.py").read_text(encoding="utf-8"))
            paths = {item["path"] for item in preview["planned"]}
            self.assertIn("bob.py", paths)
            self.assertIn("shop.py", paths)
            with self.assertRaises(AG2CError):
                flatten_cut(root, old="shop.py", side="side.py", names=["missing"])
            written = flatten_cut(root, old="shop.py", side="side.py", names=["bar"], write=True)
            self.assertTrue(written["write"])
            self.assertTrue(written["cut"])
            self.assertNotIn("from .side import bar", (root / "shop.py").read_text(encoding="utf-8"))
            self.assertIn("from .side import bar", (root / "bob.py").read_text(encoding="utf-8"))
            self.assertIn("from .shop import foo", (root / "alice.py").read_text(encoding="utf-8"))
            mixed = (root / "mixed.py").read_text(encoding="utf-8")
            self.assertIn("from .shop import foo", mixed)
            self.assertIn("from .side import bar", mixed)
            nested = (root / "nested.py").read_text(encoding="utf-8")
            self.assertIn("    from .side import bar", nested)
            self.assertTrue(flatten_door(root, old="shop.py", side="side.py", names=["bar"])["cut"])
            again = flatten_cut(root, old="shop.py", side="side.py", names=["bar"], write=True)
            self.assertTrue(again["cut"])
            self.assertEqual([], again["planned"])
            here = Path.cwd()
            os.chdir(root)
            try:
                (root / "shop.py").write_text("def foo():\n    return 1\n\nfrom .side import bar\n", encoding="utf-8")
                (root / "bob.py").write_text("from .shop import bar\n", encoding="utf-8")
                buf = io.StringIO()
                with patch("sys.stdout", buf):
                    code = main(["govern", "flatten-cut", "--old", "shop.py", "--side", "side.py", "--name", "bar", "--format", "json"])
                self.assertEqual(0, code)
                payload = json.loads(buf.getvalue())
                self.assertFalse(payload["write"])
                self.assertIn("from .side import bar", (root / "shop.py").read_text(encoding="utf-8"))
                buf = io.StringIO()
                with patch("sys.stdout", buf):
                    code = main(["govern", "flatten-cut", "--old", "shop.py", "--side", "side.py", "--name", "bar", "--write", "--format", "json"])
                self.assertEqual(0, code)
                self.assertTrue(json.loads(buf.getvalue())["write"])
                self.assertIn("from .side import bar", (root / "bob.py").read_text(encoding="utf-8"))
            finally:
                os.chdir(here)
