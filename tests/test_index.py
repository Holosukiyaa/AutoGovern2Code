import sqlite3
import tempfile
import unittest
from pathlib import Path

from ag2c.index import build_index, findings, index_path, summary, verify_freshness, verify_index

from support import write_project


class IndexTests(unittest.TestCase):
    def test_builds_complete_ownership_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, policy = write_project(Path(directory))
            path = build_index(manifest, policy)
            self.assertEqual(path, index_path(manifest))
            self.assertEqual(findings(path), [])
            value = summary(path)
            self.assertEqual(value["coverage"], {"covered": 2})
            self.assertEqual(verify_freshness(manifest, policy), [])

    def test_reports_unowned_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, policy = write_project(Path(directory), extra_file=True)
            path = build_index(manifest, policy)
            current = findings(path)
            self.assertEqual(len(current), 1)
            self.assertEqual(current[0]["finding_type"], "scope-uncovered")
            self.assertEqual(current[0]["artifact_id"], "app:src/other.py")

    def test_source_change_stales_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, policy = write_project(root)
            build_index(manifest, policy)
            (root / "src" / "api" / "service.py").write_text("VALUE = 'changed'\n", encoding="utf-8")
            errors = verify_freshness(manifest, policy)
            self.assertTrue(any("governed content changed" in error for error in errors), errors)

    def test_index_fact_mutation_breaks_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, policy = write_project(Path(directory))
            path = build_index(manifest, policy)
            connection = sqlite3.connect(path)
            connection.execute(
                "UPDATE ownership SET coverage_status = 'uncovered' "
                "WHERE artifact_id = (SELECT artifact_id FROM ownership ORDER BY artifact_id LIMIT 1)"
            )
            connection.commit()
            connection.close()
            self.assertIn("index facts digest mismatch", verify_index(path))


if __name__ == "__main__":
    unittest.main()
