import json
import sys
import tempfile
import unittest
from pathlib import Path

import bootstrap

from ag2c.acceptance import assess_verification_growth, coverage_view
from ag2c.config import load_manifest, load_policy
from ag2c.errors import AG2CError, ConfigurationError
from ag2c.seed import assess_seed, sow
from ag2c.util import path_matches

from support import record_census, write_project


class ConfigurationTests(unittest.TestCase):
    def test_globstar_matches_zero_or_more_directories(self) -> None:
        self.assertTrue(path_matches("src/__pycache__/app.pyc", "src/**/__pycache__/**"))
        self.assertTrue(path_matches("src/pkg/deep/__pycache__/app.pyc", "src/**/__pycache__/**"))
        self.assertFalse(path_matches("src/pkg/app.py", "src/**/__pycache__/**"))

    def test_loads_a_valid_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, policy = write_project(Path(directory))
            self.assertEqual(manifest.project_id, "test-project")
            self.assertEqual([target.target_id for target in manifest.targets], ["app"])
            self.assertEqual(len(policy.cards), 6)
            self.assertEqual(len(policy.checkers), 3)

    def test_rejects_duplicate_card_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _ = write_project(root)
            path = root / ".ag2c" / "policy.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["cards"].append(dict(value["cards"][0]))
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "card ids must be unique"):
                load_policy(load_manifest(manifest.path))

    def test_rejects_shell_string_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _ = write_project(root)
            path = root / ".ag2c" / "policy.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["checkers"][0]["command"] = "python -m unittest"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "list of non-empty strings"):
                load_policy(load_manifest(manifest.path))

    def test_public_contract_requires_a_real_scenario(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _ = write_project(root)
            path = root / ".ag2c" / "policy.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["contracts"][0]["scenarios"] = []
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "scenarios must not be empty"):
                load_policy(load_manifest(manifest.path))

    def test_card_provides_and_conventions_parse_without_path_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _ = write_project(root)
            path = root / ".ag2c" / "policy.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["cards"][0]["provides"] = ["路径规范化 normalize_artifact_path", r"反斜杠 C:\temp 示例"]
            value["cards"][0]["conventions"] = "状态集中 AppState；错误不炸帧"
            path.write_text(json.dumps(value), encoding="utf-8")
            policy = load_policy(load_manifest(manifest.path))
            card = policy.cards[0]
            self.assertEqual(("路径规范化 normalize_artifact_path", r"反斜杠 C:\temp 示例"), card.provides)
            self.assertEqual("状态集中 AppState；错误不炸帧", card.conventions)

    def test_card_without_provides_defaults_to_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, policy = write_project(Path(directory))
            for card in policy.cards:
                self.assertEqual((), card.provides)
                self.assertEqual("", card.conventions)

    def test_rejects_non_string_provides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _ = write_project(root)
            path = root / ".ag2c" / "policy.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["cards"][0]["provides"] = ["ok", 42]
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "provides must be a list of non-empty strings"):
                load_policy(load_manifest(manifest.path))

    def test_rejects_string_provides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _ = write_project(root)
            path = root / ".ag2c" / "policy.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["cards"][0]["provides"] = "not-a-list"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "provides must be a list of non-empty strings"):
                load_policy(load_manifest(manifest.path))


class VerificationGrowthTests(unittest.TestCase):
    def test_same_command_blob_is_unsplit_even_when_structured(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _manifest, policy = write_project(Path(directory))
            growth = assess_verification_growth(policy)
            view = coverage_view(policy)
            self.assertEqual("unsplit", growth["status"])
            self.assertEqual("same-command-blob", growth["reason"])
            self.assertEqual("structured", view["level"])
            self.assertEqual("unsplit", view["verification_growth"])

    def test_git_diff_check_alone_is_not_sliced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _ = write_project(root)
            path = root / ".ag2c" / "policy.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            diff = ["git", "diff", "--check"]
            for checker in value["checkers"]:
                checker["command"] = list(diff)
            path.write_text(json.dumps(value), encoding="utf-8")
            policy = load_policy(load_manifest(manifest.path))
            growth = assess_verification_growth(policy)
            self.assertEqual("unsplit", growth["status"])
            self.assertEqual("none", growth["reason"])
            self.assertEqual("structured", policy.coverage.level)

    def test_always_blob_plus_duplicate_scenario_stays_unsplit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _ = write_project(root, gated=True)
            path = root / ".ag2c" / "policy.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            blob = [sys.executable, "-B", "tests/run_gate.py"]
            for checker in value["checkers"]:
                checker["command"] = list(blob)
                if checker["id"] == "check.floor":
                    checker["always"] = True
            value["checkers"].append(
                {
                    "id": "check.knowledge.scripts-tests",
                    "stage": "floor",
                    "target": "app",
                    "command": list(blob),
                    "cwd": ".",
                    "timeout": 600,
                }
            )
            for card in value["cards"]:
                if card["id"] == "knowledge.worker":
                    card["checkers"] = ["check.knowledge.scripts-tests"]
            path.write_text(json.dumps(value), encoding="utf-8")
            policy = load_policy(load_manifest(manifest.path))
            growth = assess_verification_growth(policy)
            self.assertEqual("unsplit", growth["status"])
            self.assertEqual("same-command-blob", growth["reason"])

    def test_knowledge_bound_distinct_suite_is_sliced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _ = write_project(root, gated=True)
            path = root / ".ag2c" / "policy.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["checkers"].append(
                {
                    "id": "check.suite-worker",
                    "stage": "floor",
                    "target": "app",
                    "command": [sys.executable, "-B", "tests/suites.py", "worker"],
                    "cwd": ".",
                    "timeout": 300,
                }
            )
            for card in value["cards"]:
                if card["id"] == "knowledge.worker":
                    card["checkers"] = ["check.suite-worker"]
            path.write_text(json.dumps(value), encoding="utf-8")
            policy = load_policy(load_manifest(manifest.path))
            growth = assess_verification_growth(policy)
            self.assertEqual("sliced", growth["status"])
            self.assertEqual("room-bound-distinct", growth["reason"])
            self.assertIn("check.suite-worker", growth["room_bound_distinct"])
            self.assertEqual("sliced", coverage_view(policy)["verification_growth"])


class SeedLifecycleTests(unittest.TestCase):
    def test_blob_with_cards_is_mapped_not_a_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _manifest, policy = write_project(Path(directory))
            status = assess_seed(policy)
            self.assertEqual("mapped", status["phase"])
            self.assertEqual("none", status["sower"])
            self.assertFalse(status["trusted"])
            self.assertEqual("structured", status["map_level"])

    def test_no_product_tests_on_baseline_is_planted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _ = write_project(root)
            path = root / ".ag2c" / "policy.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            coverage = value.setdefault("coverage", {"strategy": "conservative", "managed_by": "human", "areas": []})
            coverage["level"] = "baseline"
            diff = ["git", "diff", "--check"]
            for checker in value["checkers"]:
                checker["command"] = list(diff)
            path.write_text(json.dumps(value), encoding="utf-8")
            policy = load_policy(load_manifest(manifest.path))
            status = assess_seed(policy)
            self.assertEqual("planted", status["phase"])
            self.assertFalse(status["trusted"])

    def test_project_suites_py_is_foreign_and_untrusted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _ = write_project(root, gated=True)
            path = root / ".ag2c" / "policy.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["checkers"].append(
                {
                    "id": "check.suite-api",
                    "stage": "floor",
                    "target": "app",
                    "command": [sys.executable, "-B", "tests/suites.py", "api"],
                    "cwd": ".",
                    "timeout": 180,
                }
            )
            for card in value["cards"]:
                if card["id"] == "knowledge.worker":
                    card["checkers"] = ["check.suite-api"]
            path.write_text(json.dumps(value), encoding="utf-8")
            policy = load_policy(load_manifest(manifest.path))
            status = assess_seed(policy)
            self.assertEqual("foreign", status["sower"])
            self.assertFalse(status["trusted"])
            self.assertIn(status["phase"], {"growing", "sliced"})

    def test_unittest_discover_checker_is_ag2c_sower(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _ = write_project(root, gated=True)
            path = root / ".ag2c" / "policy.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["checkers"].append(
                {
                    "id": "check.suite-api",
                    "stage": "floor",
                    "target": "app",
                    "command": ["python", "-B", "-m", "unittest", "discover", "-s", "scripts/tests/api", "-p", "test_*.py"],
                    "cwd": ".",
                    "timeout": 180,
                }
            )
            for card in value["cards"]:
                if card["id"] == "knowledge.worker":
                    card["checkers"] = ["check.suite-api"]
            path.write_text(json.dumps(value), encoding="utf-8")
            policy = load_policy(load_manifest(manifest.path))
            status = assess_seed(policy)
            self.assertEqual("ag2c", status["sower"])
            self.assertEqual("sliced", status["phase"])
            self.assertTrue(status["trusted"])

    def test_legacy_ag2c_seed_run_is_foreign(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _ = write_project(root, gated=True)
            path = root / ".ag2c" / "policy.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["checkers"].append(
                {
                    "id": "check.suite-api",
                    "stage": "floor",
                    "target": "app",
                    "command": ["python", "-B", "-m", "ag2c", "seed", "run", "--suite", "api"],
                    "cwd": ".",
                    "timeout": 180,
                }
            )
            for card in value["cards"]:
                if card["id"] == "knowledge.worker":
                    card["checkers"] = ["check.suite-api"]
            path.write_text(json.dumps(value), encoding="utf-8")
            policy = load_policy(load_manifest(manifest.path))
            status = assess_seed(policy)
            self.assertEqual("foreign", status["sower"])
            self.assertFalse(status["trusted"])

    def test_host_src_ag2c_is_host_sower(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, policy = write_project(root)
            (root / "src" / "ag2c").mkdir()
            (root / "src" / "ag2c" / "__init__.py").write_text("", encoding="utf-8")
            status = assess_seed(policy, project_root=root)
            self.assertEqual("host", status["sower"])
            self.assertFalse(status["trusted"])

    def test_sow_refuses_host_and_does_not_write_suites_py(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_project(root)
            (root / "src" / "ag2c").mkdir()
            (root / "src" / "ag2c" / "__init__.py").write_text("", encoding="utf-8")
            record_census(root)
            with self.assertRaisesRegex(AG2CError, "host organism is not sown"):
                sow(root, actor="tester", reason="should refuse")
            self.assertFalse((root / "tests" / "suites.py").exists())

    def test_sow_creates_ag2c_seed_run_checker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _ = write_project(root, gated=True)
            api = root / "scripts" / "tests" / "api"
            api.mkdir(parents=True)
            (api / "test_seeded.py").write_text(
                "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            path = root / ".ag2c" / "policy.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["cards"].append(
                {
                    "id": "floor.tests",
                    "type": "floor",
                    "title": "tests",
                    "summary": "Owns tests.",
                    "scopes": [{"target": "app", "include": ["scripts/tests/**"], "ownership": "primary"}],
                    "checkers": ["check.floor"],
                }
            )
            value["cards"].append(
                {
                    "id": "knowledge.scripts-tests-api",
                    "type": "knowledge",
                    "title": "API tests",
                    "summary": "API tests.",
                    "scopes": [{"target": "app", "include": ["scripts/tests/api/**"], "ownership": "reference"}],
                    "checkers": [],
                    "jurisdiction": {
                        "capability": "api",
                        "implementation": "tests.api",
                        "status": "current",
                        "entrypoints": [],
                        "grain": "subtree",
                        "meaning": "named",
                        "contract": "none",
                        "decider": "none",
                        "span": "folder",
                    },
                }
            )
            path.write_text(json.dumps(value), encoding="utf-8")
            record_census(root)
            result = sow(root, actor="tester", reason="plant api suite")
            self.assertFalse((root / "tests" / "suites.py").exists())
            self.assertIn("check.suite-api", result["created"])
            policy = load_policy(load_manifest(manifest.path))
            status = assess_seed(policy, project_root=root)
            self.assertEqual("ag2c", status["sower"])
            commands = [checker.command for checker in policy.checkers if checker.checker_id == "check.suite-api"]
            self.assertEqual(1, len(commands))
            joined = " ".join(commands[0])
            self.assertIn("unittest", joined)
            self.assertIn("discover", joined)
            self.assertIn("scripts/tests/api", joined)
            self.assertNotIn("ag2c", joined)
            self.assertTrue(status["trusted"])
