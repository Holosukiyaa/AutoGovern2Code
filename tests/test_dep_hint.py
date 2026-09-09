"""Cross-slice dependency hint tests."""

from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

import bootstrap  # noqa: F401
from support import bare_manifest

from ag2c.checks import _cross_slice_warnings, _extract_imports, _module_name_for


class ModuleNameTests(unittest.TestCase):
    def test_simple_module(self) -> None:
        self.assertEqual("ag2c.checks", _module_name_for("src/ag2c/checks.py", "src"))

    def test_nested_module(self) -> None:
        self.assertEqual("ag2c.gui.dashboard", _module_name_for("src/ag2c/gui/dashboard.py", "src"))

    def test_no_target_root(self) -> None:
        self.assertEqual("ag2c.checks", _module_name_for("ag2c/checks.py", ""))

    def test_windows_path(self) -> None:
        self.assertEqual("ag2c.checks", _module_name_for("src\\ag2c\\checks.py", "src"))


class ExtractImportsTests(unittest.TestCase):
    def test_simple_import(self) -> None:
        code = "import os\nimport sys\n"
        path = Path(tempfile.mkdtemp()) / "test.py"
        path.write_text(code, encoding="utf-8")
        imports = _extract_imports(path)
        self.assertIn("os", imports)
        self.assertIn("sys", imports)

    def test_from_import(self) -> None:
        code = "from pathlib import Path\nfrom ag2c.checks import run_checks\n"
        path = Path(tempfile.mkdtemp()) / "test.py"
        path.write_text(code, encoding="utf-8")
        imports = _extract_imports(path)
        self.assertIn("pathlib", imports)
        self.assertIn("ag2c.checks", imports)

    def test_syntax_error_returns_empty(self) -> None:
        path = Path(tempfile.mkdtemp()) / "bad.py"
        path.write_text("def broken(", encoding="utf-8")
        self.assertEqual(set(), _extract_imports(path))

    def test_nonexistent_file_returns_empty(self) -> None:
        path = Path(tempfile.mkdtemp()) / "nonexistent.py"
        self.assertEqual(set(), _extract_imports(path))


class CrossSliceWarningTests(unittest.TestCase):
    def test_empty_slice_returns_empty(self) -> None:
        manifest = bare_manifest(Path(tempfile.mkdtemp()))
        result = _cross_slice_warnings(manifest, {})
        self.assertEqual([], result)

    def test_no_python_files_returns_empty(self) -> None:
        manifest = bare_manifest(Path(tempfile.mkdtemp()))
        slice_data = {
            "entries": {
                "paths": [
                    {"path": "README.md", "target": "app"},
                ]
            }
        }
        result = _cross_slice_warnings(manifest, slice_data)
        self.assertEqual([], result)

    def test_nonexistent_changed_file_returns_empty(self) -> None:
        manifest = bare_manifest(Path(tempfile.mkdtemp()))
        slice_data = {
            "entries": {
                "paths": [
                    {"path": "src/nonexistent.py", "target": "app"},
                ]
            }
        }
        result = _cross_slice_warnings(manifest, slice_data)
        self.assertEqual([], result)


if __name__ == "__main__":
    unittest.main()
