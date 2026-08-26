import json
import sys
import tempfile
import unittest
from pathlib import Path

import bootstrap

from ag2c.checks import run_checks
from ag2c.config import load_manifest, load_policy
from ag2c.errors import ConfigurationError
from ag2c.index import build_index
from ag2c.ledger import verify_ledger
from ag2c.slicer import compile_slice

from support import write_project


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


if __name__ == "__main__":
    unittest.main()
