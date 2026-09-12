"""Tests for the mutation canary: operators, target selection, and both endings (killed = tests have teeth; survived = hollow tests alarm)."""
from __future__ import annotations

import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

import bootstrap  # noqa: F401

from ag2c.config import load_manifest, load_policy
from ag2c.mutation import (
    apply_mutation,
    find_mutations,
    mutation_targets,
    pick_mutation,
    run_mutation_canary,
)

from support import _git


def _mutation_project(root: Path, *, test_body: str):
    """Governed project whose floor.src is guarded by a real unittest checker. household_required=true：测的是金丝雀与门禁的交互，夹具必须保真。"""
    (root / ".ag2c" / "state").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "src" / "value.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests" / "test_value.py").write_text(test_body, encoding="utf-8")
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.name", "AG2C Test")
    _git(root, "config", "user.email", "ag2c-test@example.invalid")
    manifest = {
        "schema": "ag2c.manifest.v1",
        "project": {"id": "mutation-project"},
        "policy": ".ag2c/policy.json",
        "state_dir": ".ag2c/state",
        "ledger": ".ag2c/ledger.jsonl",
        "targets": [{"id": "app", "path": ".", "governed_roots": ["src", "tests"], "exclude": []}],
    }
    unittest_checker = {
        "id": "check.python",
        "stage": "floor",
        "target": "app",
        "command": [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests"],
        "cwd": ".",
        "timeout": 120,
        "always": True,
        "parse": "unittest",
    }
    policy = {
        "schema": "ag2c.policy.v1",
        "household_required": True,
        "cards": [
            {"id": "constitution.project", "type": "constitution", "title": "C", "summary": "S"},
            {
                "id": "floor.src",
                "type": "floor",
                "title": "Src",
                "summary": "Owns src.",
                "scopes": [{"target": "app", "include": ["src/**"], "ownership": "primary"}],
                "checkers": ["check.python"],
            },
            {
                "id": "floor.tests",
                "type": "floor",
                "title": "Tests",
                "summary": "Owns tests.",
                "scopes": [{"target": "app", "include": ["tests/**"], "ownership": "primary"}],
                "checkers": ["check.python"],
            },
            {
                "id": "knowledge.tests",
                "type": "knowledge",
                "title": "tests room",
                "summary": "Tests room.",
                "scopes": [{"target": "app", "include": ["tests/**"], "ownership": "reference"}],
                "references": ["tests/test_value.py"],
                "jurisdiction": {
                    "capability": "tests",
                    "implementation": "tests",
                    "status": "current",
                    "grain": "directory",
                    "meaning": "named",
                    "contract": "none",
                    "decider": "none",
                    "span": "folder",
                },
            },
            {
                "id": "knowledge.src",
                "type": "knowledge",
                "title": "src room",
                "summary": "Src room.",
                "scopes": [{"target": "app", "include": ["src/**"], "ownership": "reference"}],
                "references": ["src/value.py"],
                "jurisdiction": {
                    "capability": "src",
                    "implementation": "src",
                    "status": "current",
                    "grain": "directory",
                    "meaning": "named",
                    "contract": "none",
                    "decider": "none",
                    "span": "folder",
                },
            },
        ],
        "relations": [
            {"source": "knowledge.tests", "type": "explains", "target": "floor.tests"},
            {"source": "knowledge.src", "type": "explains", "target": "floor.src"},
        ],
        "contracts": [],
        "checkers": [unittest_checker],
    }
    (root / ".ag2c" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / ".ag2c" / "policy.json").write_text(json.dumps(policy), encoding="utf-8")
    _git(root, "add", "--all")
    _git(root, "commit", "-m", "initial")
    loaded = load_manifest(root / ".ag2c" / "manifest.json")
    return loaded, load_policy(loaded)


_TEETH_TEST = (
    "import unittest\nfrom src.value import VALUE\n\n"
    "class ValueTests(unittest.TestCase):\n"
    "    def test_value(self):\n"
    "        self.assertEqual(VALUE, 1)\n"
)
_HOLLOW_TEST = (
    "import unittest\n\n"
    "class ValueTests(unittest.TestCase):\n"
    "    def test_value(self):\n"
    "        self.assertEqual(1, 1)\n"
)


class MutationOperatorTests(unittest.TestCase):
    def test_comparison_flip(self) -> None:
        mutations = find_mutations("x == 1\n")
        comparison = [m for m in mutations if m.original == "=="]
        self.assertEqual(1, len(comparison))
        self.assertEqual("!=", comparison[0].replacement)
        mutated = apply_mutation("x == 1\n", comparison[0])
        self.assertEqual("x != 1\n", mutated)
        compile(mutated, "<mutation>", "exec")

    def test_boolean_flip(self) -> None:
        mutations = find_mutations("flag = True\n")
        self.assertEqual(["True"], [m.original for m in mutations])
        self.assertEqual("flag = False\n", apply_mutation("flag = True\n", mutations[0]))

    def test_number_bump(self) -> None:
        mutations = find_mutations("VALUE = 1\n")
        self.assertEqual(["1"], [m.original for m in mutations])
        self.assertEqual("VALUE = 2\n", apply_mutation("VALUE = 1\n", mutations[0]))

    def test_strings_and_comments_are_not_candidates(self) -> None:
        self.assertEqual([], find_mutations("x = 'a == b'  # True == 1\n"))

    def test_no_candidate_returns_none(self) -> None:
        self.assertIsNone(pick_mutation("x = 'hello'\n", random.Random(0)))

    def test_position_mismatch_raises(self) -> None:
        from ag2c.mutation import Mutation

        with self.assertRaises(AssertionError):
            apply_mutation("x = 1\n", Mutation(1, 0, "==", "!=", "bogus"))

    def test_pick_is_seeded(self) -> None:
        source = "a = 1\nb = 2\nc = True\n"
        self.assertEqual(
            pick_mutation(source, random.Random(7)),
            pick_mutation(source, random.Random(7)),
        )


class TargetSelectionTests(unittest.TestCase):
    def test_only_tested_product_code_is_a_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, policy = _mutation_project(root, test_body=_TEETH_TEST)
            targets = mutation_targets(manifest, policy)
            self.assertEqual([str(root / "src" / "value.py")], [str(path) for path in targets])


class MutationCanaryEndToEndTests(unittest.TestCase):
    def test_mutation_killed_when_tests_have_teeth(self) -> None:
        from ag2c.household_commands import review_census
        from ag2c.index import verify_freshness

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, policy = _mutation_project(root, test_body=_TEETH_TEST)
            # 健康项目：金丝雀运行前所有房间已复核
            review_census(root, card_ids=[], all_cards=True, actor="test", reason="initial review")
            result, exit_code = run_mutation_canary(manifest, policy, actor="test", reason="e2e teeth", seed=0)
            self.assertEqual(0, exit_code)
            self.assertEqual("passed", result["canary"])
            self.assertIn("check.python", result["caught_by"])
            self.assertIn("数字 1→2", result["mutation"])
            # 原文还原，现场无残留
            self.assertEqual("VALUE = 1\n", (root / "src" / "value.py").read_text(encoding="utf-8"))
            self.assertEqual([], verify_freshness(manifest, policy))
            events = [
                json.loads(line)
                for line in (root / ".ag2c" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            canary_events = [e for e in events if e.get("event_type") == "canary"]
            self.assertEqual(1, len(canary_events))
            self.assertEqual("mutation", canary_events[0]["payload"]["mode"])

    def test_mutation_survives_hollow_tests_and_alarms(self) -> None:
        from ag2c.household_commands import review_census

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, policy = _mutation_project(root, test_body=_HOLLOW_TEST)
            review_census(root, card_ids=[], all_cards=True, actor="test", reason="initial review")
            result, exit_code = run_mutation_canary(manifest, policy, actor="test", reason="e2e hollow", seed=0)
            self.assertEqual(1, exit_code)
            self.assertEqual("failed", result["canary"])
            self.assertEqual([], result["caught_by"])
            self.assertEqual("VALUE = 1\n", (root / "src" / "value.py").read_text(encoding="utf-8"))

    def test_crlf_file_restored_byte_identical(self) -> None:
        """CRLF 文件的还原必须是字节级一致——换行转换会让 Git 看到幻影改动。"""
        from ag2c.household_commands import review_census

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, policy = _mutation_project(root, test_body=_TEETH_TEST)
            crlf = b"# header\r\nVALUE = 1\r\n"
            (root / "src" / "value.py").write_bytes(crlf)
            _git(root, "add", "--all")
            _git(root, "commit", "-m", "crlf")
            review_census(root, card_ids=[], all_cards=True, actor="test", reason="initial review")
            run_mutation_canary(manifest, policy, actor="test", reason="e2e crlf", seed=0)
            self.assertEqual(crlf, (root / "src" / "value.py").read_bytes())


class TargetedCanaryTests(unittest.TestCase):
    """定向变异金丝雀：危房销案靠同文件复跑，随机选文件可能永远摇不中。"""

    def test_target_picks_the_named_file(self) -> None:
        from ag2c.household_commands import review_census

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, policy = _mutation_project(root, test_body=_TEETH_TEST)
            review_census(root, card_ids=[], all_cards=True, actor="test", reason="initial review")
            result, exit_code = run_mutation_canary(
                manifest, policy, actor="test", reason="targeted", target="app:src/value.py"
            )
            self.assertEqual(0, exit_code)
            self.assertEqual("passed", result["canary"])
            self.assertEqual("app:src/value.py", result["target"])

    def test_target_accepts_bare_relative_path(self) -> None:
        from ag2c.household_commands import review_census

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, policy = _mutation_project(root, test_body=_TEETH_TEST)
            review_census(root, card_ids=[], all_cards=True, actor="test", reason="initial review")
            result, exit_code = run_mutation_canary(
                manifest, policy, actor="test", reason="targeted", target="src/value.py"
            )
            self.assertEqual(0, exit_code)
            self.assertEqual("app:src/value.py", result["target"])

    def test_target_outside_mutable_set_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, policy = _mutation_project(root, test_body=_TEETH_TEST)
            # tests/ 里的文件不是可变异目标（变异测试文件证明不了产品代码被 pinning）
            result, exit_code = run_mutation_canary(
                manifest, policy, actor="test", reason="targeted", target="app:tests/test_value.py"
            )
            self.assertEqual(2, exit_code)
            self.assertEqual("error", result["canary"])
            self.assertIn("target-not-mutable", result["reason"])

    def test_target_without_mutation_point_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, policy = _mutation_project(root, test_body=_TEETH_TEST)
            (root / "src" / "value.py").write_text("NAME = 'hello'\n", encoding="utf-8")
            _git(root, "add", "--all")
            _git(root, "commit", "-m", "no mutation point")
            result, exit_code = run_mutation_canary(
                manifest, policy, actor="test", reason="targeted", target="app:src/value.py"
            )
            self.assertEqual(2, exit_code)
            self.assertEqual("error", result["canary"])
            self.assertIn("src/value.py", result["reason"])
