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

    def test_room_bound_unittest_checker_runs_only_when_the_room_is_sliced(self) -> None:
        body = "import sys; print('FAIL: test_worker (tests.test_worker)', file=sys.stderr); sys.exit(1)"
        jurisdiction = {
            "capability": "worker",
            "implementation": "worker.main",
            "status": "current",
            "entrypoints": [],
            "grain": "subtree",
            "meaning": "named",
            "contract": "none",
            "decider": "none",
            "span": "folder",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_project(root)
            # Only directory households (knowledge cards with a jurisdiction) may own checkers.
            _add_checker(root, _unittest_checker(body), bind_to="knowledge.worker")
            manifest = load_manifest(root / ".ag2c" / "manifest.json")
            with self.assertRaisesRegex(ConfigurationError, "cannot own checkers"):
                load_policy(manifest)
            policy_path = root / ".ag2c" / "policy.json"
            raw = json.loads(policy_path.read_text(encoding="utf-8"))
            for card in raw["cards"]:
                if card.get("id") == "knowledge.worker":
                    card["jurisdiction"] = jurisdiction
            policy_path.write_text(json.dumps(raw), encoding="utf-8")
            manifest, policy = _reload(root)
            build_index(manifest, policy)

            # Slicing the api side never selects knowledge.worker, so its room checker stays out.
            api_slice = compile_slice(manifest, policy, path_specs=["app:src/api/service.py"])
            self.assertNotIn("knowledge.worker", {card["id"] for card in api_slice["cards"]})
            self.assertNotIn("check.tests", {item["id"] for item in api_slice["check_plan"]})

            # Slicing the worker room selects the card and its zero-regression checker.
            worker_slice = compile_slice(manifest, policy, path_specs=["app:src/worker/job.py"])
            self.assertIn("knowledge.worker", {card["id"] for card in worker_slice["cards"]})
            self.assertIn("check.tests", {item["id"] for item in worker_slice["check_plan"]})
            report = run_checks(manifest, policy, worker_slice)
            result = next(item for item in report["results"] if item["id"] == "check.tests")
            self.assertEqual("failed", result["status"])
            self.assertEqual(["test_worker (tests.test_worker)"], result["new_failures"])
            accept_test_baseline(manifest, policy, [], actor="tester", reason="record room debt")
            report = run_checks(manifest, policy, worker_slice)
            result = next(item for item in report["results"] if item["id"] == "check.tests")
            self.assertEqual("passed", result["status"])

    def test_docs_only_diff_skips_always_test_suites(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_project(root)
            (root / "docs").mkdir()
            (root / "docs" / "guide.md").write_text("# guide\n", encoding="utf-8")
            _add_checker(root, _unittest_checker("print('ok')", always=True))
            manifest, policy = _reload(root)
            build_index(manifest, policy)

            docs_slice = compile_slice(manifest, policy, path_specs=["app:docs/guide.md"])
            report = run_checks(manifest, policy, docs_slice)
            result = next(item for item in report["results"] if item["id"] == "check.tests")
            self.assertEqual("skipped", result["status"])
            self.assertIn("docs-only", result["skip_reason"])

            code_slice = compile_slice(manifest, policy, path_specs=["app:src/api/service.py"])
            report = run_checks(manifest, policy, code_slice)
            result = next(item for item in report["results"] if item["id"] == "check.tests")
            self.assertEqual("passed", result["status"])

    def test_neighbour_room_checkers_stay_out_of_the_check_plan(self) -> None:
        jurisdiction = {
            "capability": "worker",
            "implementation": "worker.main",
            "status": "current",
            "entrypoints": [],
            "grain": "subtree",
            "meaning": "named",
            "contract": "none",
            "decider": "none",
            "span": "folder",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_project(root)
            _add_checker(root, _unittest_checker("print('ok')"), bind_to="knowledge.worker")
            policy_path = root / ".ag2c" / "policy.json"
            raw = json.loads(policy_path.read_text(encoding="utf-8"))
            for card in raw["cards"]:
                if card.get("id") == "knowledge.worker":
                    card["jurisdiction"] = jurisdiction
            # Both rooms explain the SAME floor, like every src room explains floor.src.
            raw["relations"].append({"source": "knowledge.worker", "type": "explains", "target": "floor.api"})
            # The api side needs its own household so the enforce-mode gate sees owned code.
            raw["cards"].append(
                {
                    "id": "knowledge.api",
                    "type": "knowledge",
                    "title": "API navigation",
                    "summary": "Explains api source.",
                    "scopes": [{"target": "app", "include": ["src/api/**"], "ownership": "reference"}],
                    "references": [],
                    "jurisdiction": {**jurisdiction, "capability": "api", "implementation": "api.main"},
                }
            )
            raw["relations"].append({"source": "knowledge.api", "type": "explains", "target": "floor.api"})
            policy_path.write_text(json.dumps(raw), encoding="utf-8")
            manifest, policy = _reload(root)
            build_index(manifest, policy)

            api_slice = compile_slice(manifest, policy, path_specs=["app:src/api/service.py"])
            # The neighbour room is still knowledge context for the agent...
            self.assertIn("knowledge.worker", {card["id"] for card in api_slice["cards"]})
            # ...but a suite belongs to the room that owns the change: it must not run.
            self.assertNotIn("check.tests", {item["id"] for item in api_slice["check_plan"]})

            worker_slice = compile_slice(manifest, policy, path_specs=["app:src/worker/job.py"])
            self.assertIn("check.tests", {item["id"] for item in worker_slice["check_plan"]})

            # The household gate owes nothing from a context room, but a directly
            # touched room must have every bound checker selected.
            from ag2c.households import enforce_households

            raw["household_required"] = True
            policy_path.write_text(json.dumps(raw), encoding="utf-8")
            manifest, policy = _reload(root)
            build_index(manifest, policy)
            import subprocess

            subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
            from ag2c.household_commands import review_census

            review_census(root, card_ids=["knowledge.api"], all_cards=False, actor="tester", reason="record api room")
            manifest, policy = _reload(root)
            build_index(manifest, policy)
            api_slice = compile_slice(manifest, policy, path_specs=["app:src/api/service.py"])
            enforce_households(manifest, policy, api_slice, {item["id"] for item in api_slice["check_plan"]})
            worker_slice = compile_slice(manifest, policy, path_specs=["app:src/worker/job.py"])
            with self.assertRaisesRegex(AG2CError, "implementation-check-not-selected:knowledge.worker"):
                enforce_households(manifest, policy, worker_slice, {"check.floor"})

    def test_room_tool_checkers_never_mismatch_the_household_implementation(self) -> None:
        from ag2c.households import census_report

        jurisdiction = {
            "capability": "worker",
            "implementation": "worker.main",
            "status": "current",
            "entrypoints": [],
            "grain": "subtree",
            "meaning": "named",
            "contract": "none",
            "decider": "none",
            "span": "folder",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_project(root)
            # A plain unittest suite (no implementation claim) bound to a room
            # whose jurisdiction names a product implementation.
            _add_checker(root, _unittest_checker("print('ok')"), bind_to="knowledge.worker")
            policy_path = root / ".ag2c" / "policy.json"
            raw = json.loads(policy_path.read_text(encoding="utf-8"))
            for card in raw["cards"]:
                if card.get("id") == "knowledge.worker":
                    card["jurisdiction"] = jurisdiction
            policy_path.write_text(json.dumps(raw), encoding="utf-8")
            manifest, policy = _reload(root)
            build_index(manifest, policy)

            report = census_report(manifest, policy)
            household = next(item for item in report["households"] if item["id"] == "knowledge.worker")
            self.assertNotIn("implementation-check-mismatch", {issue["code"] for issue in household["issues"]})

            # A checker claiming a DIFFERENT implementation still mismatches.
            _add_checker(root, _unittest_checker("print('ok')", id="check.other", implementation="other.impl"), bind_to="knowledge.worker")
            manifest, policy = _reload(root)
            build_index(manifest, policy)
            report = census_report(manifest, policy)
            household = next(item for item in report["households"] if item["id"] == "knowledge.worker")
            self.assertIn("implementation-check-mismatch", {issue["code"] for issue in household["issues"]})

            # A machine-contract room is not satisfied by room tools alone.
            raw = json.loads(policy_path.read_text(encoding="utf-8"))
            for card in raw["cards"]:
                if card.get("id") == "knowledge.worker":
                    card["jurisdiction"] = {**jurisdiction, "contract": "machine"}
                    card["checkers"] = ["check.tests"]
            for checker in raw["checkers"]:
                if checker.get("id") == "check.other":
                    raw["checkers"].remove(checker)
            policy_path.write_text(json.dumps(raw), encoding="utf-8")
            manifest, policy = _reload(root)
            build_index(manifest, policy)
            report = census_report(manifest, policy)
            household = next(item for item in report["households"] if item["id"] == "knowledge.worker")
            codes = {issue["code"] for issue in household["issues"]}
            self.assertIn("implementation-check-missing", codes)
            self.assertNotIn("implementation-check-mismatch", codes)

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

    def test_update_checker_creates_room_suite_checkers(self) -> None:
        import subprocess

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_project(root)
            subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)

            # Unknown id without a command is still refused.
            with self.assertRaisesRegex(AG2CError, "pass --command to create"):
                update_checker(root, checker_id="check.suite-worker", actor="tester", reason="x", parse="unittest")

            # Policy forbids orphaned checkers: creating requires a binding.
            with self.assertRaisesRegex(AG2CError, "must be bound to a card"):
                update_checker(root, checker_id="check.suite-worker", actor="tester", reason="x", command=["python", "-B", "tests/suites.py", "worker"])
            with self.assertRaisesRegex(AG2CError, "unknown cards: floor.nope"):
                update_checker(root, checker_id="check.suite-worker", actor="tester", reason="x", command=["python", "-B", "tests/suites.py", "worker"], bind=["floor.nope"])

            # Unknown id + command + bind creates a floor checker with the gate fields applied.
            result = update_checker(
                root,
                checker_id="check.suite-worker",
                actor="tester",
                reason="split worker suite out of the full run",
                command=["python", "-B", "tests/suites.py", "worker"],
                parse="unittest",
                timeout=300,
                bind=["floor.api"],
            )
            self.assertEqual("create", result["action"])
            self.assertTrue(result["changes"]["created"])
            self.assertEqual(["floor.api"], result["changes"]["bound"])
            _, policy = _reload(root)
            checker = policy.checker("check.suite-worker")
            self.assertEqual("floor", checker.stage)
            self.assertEqual(("python", "-B", "tests/suites.py", "worker"), checker.command)
            self.assertEqual("unittest", checker.parse)
            self.assertEqual(300, checker.timeout)
            self.assertFalse(checker.always)
            self.assertIn("check.suite-worker", list(policy.card("floor.api").checkers))

            # A created checker's command can be updated in place.
            result = update_checker(
                root,
                checker_id="check.suite-worker",
                actor="tester",
                reason="point at the api suite",
                command=["python", "-B", "tests/suites.py", "api"],
            )
            self.assertEqual("update", result["action"])
            _, policy = _reload(root)
            checker = policy.checker("check.suite-worker")
            self.assertEqual(("python", "-B", "tests/suites.py", "api"), checker.command)

            # Floor cards may only bind floor checkers: moving the stage while
            # bound is refused by policy validation AND rolled back on disk.
            with self.assertRaisesRegex(AG2CError, "can only bind floor checkers"):
                update_checker(root, checker_id="check.suite-worker", actor="tester", reason="bad stage move", stage="boundary")
            _, policy = _reload(root)
            self.assertEqual("floor", policy.checker("check.suite-worker").stage)

            # Re-binding to a card that already owns the checker is idempotent.
            result = update_checker(root, checker_id="check.suite-worker", actor="tester", reason="re-bind is a no-op", bind=["floor.api"])
            self.assertNotIn("bound", result["changes"])

            with self.assertRaisesRegex(AG2CError, "nonempty JSON array of strings"):
                update_checker(root, checker_id="check.suite-worker", actor="tester", reason="x", command=[])
            with self.assertRaisesRegex(AG2CError, "unsupported checker stage"):
                update_checker(root, checker_id="check.suite-worker", actor="tester", reason="x", stage="outer-space")


if __name__ == "__main__":
    unittest.main()
