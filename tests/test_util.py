"""util.py 共享工具的直接测试。"""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import bootstrap  # noqa: F401

from ag2c.errors import AG2CError
from ag2c.util import read_json


class ReadJsonTests(unittest.TestCase):
    """合并自 govern/enrollment 双份 _read_json 的共享实现（首次拆迁）。"""

    def test_reads_object(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.json"
            path.write_text('{"k": 1}', encoding="utf-8")
            self.assertEqual({"k": 1}, read_json(path, what="governance file"))

    def test_corrupt_file_error_carries_label(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(AG2CError) as ctx:
                read_json(path, what="AG2C lifecycle file")
            self.assertIn("cannot read AG2C lifecycle file", str(ctx.exception))

    def test_non_object_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "list.json"
            path.write_text("[1, 2]", encoding="utf-8")
            with self.assertRaises(AG2CError) as ctx:
                read_json(path, what="governance file")
            self.assertIn("governance file must contain an object", str(ctx.exception))
