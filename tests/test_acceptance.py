from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import bootstrap

from ag2c.acceptance import assess_product
from ag2c.enrollment import enroll_project
from ag2c.govern import pending_updates
from ag2c.tasks import evidence

from support import git_project, write_project


class ProductAcceptanceTests(unittest.TestCase):
    def test_baseline_project_stays_undeclared(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "project")
            enroll_project(root, project_id="baseline-demo", skill_root=workspace / "skills")

            report = evidence(root)
            self.assertEqual("undeclared", report["product"]["status"])
            self.assertFalse(report["product"]["declared"])
            kinds = {item["kind"] for item in pending_updates(root)["items"]}
            self.assertIn("undeclared-product", kinds)

    def test_stale_rules_block_declared_product_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, policy = write_project(Path(directory))
            value = assess_product(policy, knowledge=[{"id": "knowledge.worker", "status": "stale"}])
            self.assertEqual("blocked", value["status"])
            self.assertTrue(value["declared"])
            self.assertEqual(["knowledge.worker"], value["stale_rules"])

    def test_declared_product_checks_can_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, policy = write_project(Path(directory))
            value = assess_product(
                policy,
                verification={
                    "checker_results": [
                        {"id": "check.boundary", "stage": "boundary", "status": "passed"},
                        {"id": "check.scenario", "stage": "scenario", "status": "passed"},
                    ]
                },
            )
            self.assertEqual("checked", value["status"])
