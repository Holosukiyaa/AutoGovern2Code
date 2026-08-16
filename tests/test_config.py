import json
import tempfile
import unittest
from pathlib import Path

from ag2c.config import load_manifest, load_policy
from ag2c.errors import ConfigurationError
from ag2c.util import path_matches

from support import write_project


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


if __name__ == "__main__":
    unittest.main()
