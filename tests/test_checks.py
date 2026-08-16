import json
import tempfile
import unittest
from pathlib import Path

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
