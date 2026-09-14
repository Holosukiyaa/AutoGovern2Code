"""Keep tests/suites.py honest: every test module is in exactly one suite."""
from __future__ import annotations

import unittest
from pathlib import Path

import bootstrap  # noqa: F401

import suites


class SuiteMappingTests(unittest.TestCase):
    def test_every_test_module_is_in_exactly_one_suite(self) -> None:
        tests_dir = Path(__file__).resolve().parent
        on_disk = {path.stem for path in tests_dir.glob("test_*.py")}
        mapped = [module for members in suites.SUITES.values() for module in members]
        self.assertEqual(sorted(on_disk), sorted(set(mapped)), "suite mapping drifted from tests/ on disk")
        self.assertEqual(len(mapped), len(set(mapped)), "a test module appears in two suites")

    def test_fast_suite_stays_fast(self) -> None:
        slow = {"test_rehome", "test_enrollment", "test_checks", "test_receipts", "test_storage", "test_gitops", "test_desktop"}
        self.assertFalse(slow & set(suites.SUITES["fast"]), "slow integration module leaked into the fast suite")

    def test_list_output(self) -> None:
        self.assertEqual(0, suites.main(["suites.py", "fast", "--list"]))
        self.assertEqual(2, suites.main(["suites.py", "nope"]))

    def test_suite_bind_matches_suites_py(self) -> None:
        from ag2c.suite_bind import DEFAULT_SUITES, suite_checker_ids_for_paths

        self.assertEqual(suites.SUITES, DEFAULT_SUITES)
        self.assertEqual({"check.suite-gui"}, suite_checker_ids_for_paths(["tests/test_desktop.py"]))
        self.assertNotIn("check.suite-storage", suite_checker_ids_for_paths(["tests/test_desktop.py"]))
        self.assertEqual(set(), suite_checker_ids_for_paths(["tests/test_cli.py"]))
