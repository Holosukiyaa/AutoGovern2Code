import json
import sys
import tempfile
import unittest
from pathlib import Path

import bootstrap

from ag2c.checks import accept_test_baseline, load_test_baseline, parse_unittest_failures, run_checks
from ag2c.config import load_manifest, load_policy
from ag2c.errors import AG2CError, ConfigurationError
from ag2c.govern import update_checker
from ag2c.index import build_index
from ag2c.ledger import verify_ledger
from ag2c.slicer import compile_slice

from support import write_project


def _add_checker(root: Path, checker: dict, *, bind_to: str = "floor.api"):
    policy_path = root / ".ag2c" / "policy.json"
    raw = json.loads(policy_path.read_text(encoding="utf-8"))
    for card in raw["cards"]:
        if card.get("id") == bind_to:
            card.setdefault("checkers", []).append(checker["id"])
    raw["checkers"].append(checker)
    policy_path.write_text(json.dumps(raw), encoding="utf-8")


def _reload(root: Path):
    manifest = load_manifest(root / ".ag2c" / "manifest.json")
    return manifest, load_policy(manifest)


def _unittest_checker(command_body: str, **extra) -> dict:
    checker = {
        "id": "check.tests",
        "stage": "floor",
        "target": "app",
        "command": [sys.executable, "-c", command_body],
        "cwd": ".",
        "timeout": 30,
        "parse": "unittest",
    }
    checker.update(extra)
    return checker


class CheckerTests(unittest.TestCase):
    def test_all_mode_records_complete_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, policy = write_project(Path(directory))
            build_index(manifest, policy)
            entry_slice = compile_slice(manifest, policy, all_mode=True)
            report = run_checks(manifest, policy, entry_slice, all_mode=True)
            self.assertEqual(report["acceptance"]["complete"], "passed")
            self.assertEqual({result["status"] for result in report["results"]}, {"passed"})
            self.assertEqual(verify_ledger(manifest.ledger_path), [])
            self.assertEqual(report["ledger_sequence"], 1)
            self.assertIn("python", report["environment"])
            self.assertTrue(report["environment"]["has_git"])

    def test_checker_can_skip_with_an_explicit_reason(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, policy = write_project(Path(directory))
            raw = json.loads(policy.path.read_text(encoding="utf-8"))
            for card in raw["cards"]:
                if card.get("id") == "floor.api":
                    card.setdefault("checkers", []).append("check.skip")
                    break
            raw["checkers"].append(
                {
                    "id": "check.skip",
                    "stage": "floor",
                    "target": "app",
                    "command": [
                        sys.executable,
                        "-c",
                        "import sys; print('AG2C_SKIP: no toolchain'); sys.exit(78)",
                    ],
                    "cwd": ".",
                    "timeout": 30,
                }
            )
            policy.path.write_text(json.dumps(raw), encoding="utf-8")
            manifest = load_manifest(manifest.path)
            policy = load_policy(manifest)
            build_index(manifest, policy)
            entry_slice = compile_slice(manifest, policy, all_mode=True)
            report = run_checks(manifest, policy, entry_slice, all_mode=True)
            skipped = next(item for item in report["results"] if item["id"] == "check.skip")
            self.assertEqual("skipped", skipped["status"])
            self.assertEqual("no toolchain", skipped["skip_reason"])
            self.assertEqual("skipped", report["acceptance"]["floor"])
            self.assertEqual("not-run", report["acceptance"]["complete"])

    def test_floor_without_checker_is_invalid_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _ = write_project(root)
            policy_path = root / ".ag2c" / "policy.json"
            value = json.loads(policy_path.read_text(encoding="utf-8"))
            for card in value["cards"]:
                card.pop("checkers", None)
            value["checkers"] = []
            policy_path.write_text(json.dumps(value), encoding="utf-8")
            manifest = load_manifest(manifest.path)
            with self.assertRaisesRegex(ConfigurationError, "requires at least one floor checker"):
                load_policy(manifest)

    def test_always_checker_joins_the_check_plan_without_card_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_project(root)
            always_checker = _unittest_checker("print('ok')", always=True)
            _add_checker(root, always_checker, bind_to="floor.worker")
            plain = _unittest_checker("print('ok')")
            plain["id"] = "check.plain"
            plain.pop("parse")
            _add_checker(root, plain, bind_to="floor.worker")
            manifest, policy = _reload(root)
            build_index(manifest, policy)
            # floor.worker depends_on floor.api, so slicing the api side never selects floor.worker.
            entry_slice = compile_slice(manifest, policy, path_specs=["app:src/api/service.py"])
            self.assertNotIn("floor.worker", {card["id"] for card in entry_slice["cards"]})
            plan = {item["id"]: item for item in entry_slice["check_plan"]}
            self.assertIn("check.tests", plan)
            self.assertEqual(["always"], plan["check.tests"]["selection_reasons"])
            self.assertNotIn("check.plain", plan)

    def test_checker_always_and_parse_are_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_project(root)
            _add_checker(root, _unittest_checker("print('ok')", always="yes"))
            manifest = load_manifest(root / ".ag2c" / "manifest.json")
            with self.assertRaisesRegex(ConfigurationError, "always must be a boolean"):
                load_policy(manifest)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_project(root)
            _add_checker(root, _unittest_checker("print('ok')", parse="pytest"))
            manifest = load_manifest(root / ".ag2c" / "manifest.json")
            with self.assertRaisesRegex(ConfigurationError, "unsupported parse mode"):
                load_policy(manifest)

    def test_unittest_new_failures_block_until_baselines(self) -> None:
        body = "import sys; print('FAIL: test_a (tests.test_a)', file=sys.stderr); sys.exit(1)"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_project(root)
            _add_checker(root, _unittest_checker(body, always=True))
            manifest, policy = _reload(root)
            build_index(manifest, policy)
            entry_slice = compile_slice(manifest, policy, all_mode=True)
            report = run_checks(manifest, policy, entry_slice, all_mode=True)
            result = next(item for item in report["results"] if item["id"] == "check.tests")
            self.assertEqual("failed", result["status"])
            self.assertEqual(["test_a (tests.test_a)"], result["new_failures"])

            accepted = accept_test_baseline(manifest, policy, [], actor="tester", reason="record known debt")
            self.assertEqual(1, accepted["accepted"]["check.tests"]["failures"])
            self.assertEqual(["test_a (tests.test_a)"], load_test_baseline(manifest)["check.tests"])

            report = run_checks(manifest, policy, entry_slice, all_mode=True)
            result = next(item for item in report["results"] if item["id"] == "check.tests")
            self.assertEqual("passed", result["status"])
            self.assertEqual(["test_a (tests.test_a)"], result["baseline_failures"])
            self.assertIn("baseline", result["baseline_note"])

    def test_unittest_fixed_failures_shrink_the_baseline(self) -> None:
        failing = "import sys; print('FAIL: test_a (tests.test_a)', file=sys.stderr); sys.exit(1)"
        passing = "print('ok')"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_project(root)
            _add_checker(root, _unittest_checker(failing, always=True))
            manifest, policy = _reload(root)
            build_index(manifest, policy)
            accept_test_baseline(manifest, policy, [], actor="tester", reason="record known debt")
            self.assertIn("check.tests", load_test_baseline(manifest))

            policy_path = root / ".ag2c" / "policy.json"
            raw = json.loads(policy_path.read_text(encoding="utf-8"))
            for item in raw["checkers"]:
                if item["id"] == "check.tests":
                    item["command"] = [sys.executable, "-c", passing]
            policy_path.write_text(json.dumps(raw), encoding="utf-8")
            manifest, policy = _reload(root)
            build_index(manifest, policy)
            entry_slice = compile_slice(manifest, policy, all_mode=True)
            report = run_checks(manifest, policy, entry_slice, all_mode=True)
            result = next(item for item in report["results"] if item["id"] == "check.tests")
            self.assertEqual("passed", result["status"])
            self.assertEqual(["test_a (tests.test_a)"], result["fixed_failures"])
            self.assertEqual({}, load_test_baseline(manifest))

    def test_unittest_crash_without_parseable_failures_stays_failed(self) -> None:
        body = "import sys; print('boom', file=sys.stderr); sys.exit(2)"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_project(root)
            _add_checker(root, _unittest_checker(body, always=True))
            manifest, policy = _reload(root)
            build_index(manifest, policy)
            entry_slice = compile_slice(manifest, policy, all_mode=True)
            report = run_checks(manifest, policy, entry_slice, all_mode=True)
            result = next(item for item in report["results"] if item["id"] == "check.tests")
            self.assertEqual("failed", result["status"])
            self.assertIn("hard error", result["stderr"])

    def test_parse_unittest_failures_reads_fail_and_error_lines(self) -> None:
        output = "FAIL: test_a (tests.test_a)\nERROR: test_b (tests.test_b)\nrandom noise\nFAILED (failures=2)\n"
        self.assertEqual(["test_a (tests.test_a)", "test_b (tests.test_b)"], parse_unittest_failures(output))

    def test_update_checker_adjusts_gate_behavior(self) -> None:
        import subprocess

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_project(root)
            subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
            _add_checker(root, _unittest_checker("print('ok')"))
            result = update_checker(root, checker_id="check.tests", actor="tester", reason="promote to gate", always=True, parse="unittest", timeout=120)
            self.assertEqual({"always": True, "parse": "unittest", "timeout": 120}, result["changes"])
            _, policy = _reload(root)
            checker = policy.checker("check.tests")
            self.assertTrue(checker.always)
            self.assertEqual("unittest", checker.parse)
            self.assertEqual(120, checker.timeout)

            result = update_checker(root, checker_id="check.tests", actor="tester", reason="demote", always=False, parse="none")
            _, policy = _reload(root)
            checker = policy.checker("check.tests")
            self.assertFalse(checker.always)
            self.assertEqual("", checker.parse)

            with self.assertRaisesRegex(AG2CError, "unknown checker"):
                update_checker(root, checker_id="check.nope", actor="tester", reason="x", always=True)
            with self.assertRaisesRegex(AG2CError, "nothing to change"):
                update_checker(root, checker_id="check.tests", actor="tester", reason="x")


if __name__ == "__main__":
    unittest.main()
