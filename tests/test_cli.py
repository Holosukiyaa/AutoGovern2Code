import tempfile
import unittest
from pathlib import Path

from deg.cli import main


class CLITests(unittest.TestCase):
    def test_init_creates_starter_policy_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(main(["init", str(root), "--project-id", "starter"]), 0)
            self.assertTrue((root / ".deg" / "manifest.json").is_file())
            self.assertTrue((root / ".deg" / "policy.json").is_file())
            self.assertEqual(main(["init", str(root), "--project-id", "starter"]), 2)


if __name__ == "__main__":
    unittest.main()
