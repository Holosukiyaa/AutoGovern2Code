import json
import tempfile
import unittest
from pathlib import Path

import bootstrap

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


if __name__ == "__main__":
    unittest.main()
