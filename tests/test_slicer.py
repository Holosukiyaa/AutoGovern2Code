import tempfile
import unittest
from pathlib import Path

import bootstrap

from ag2c.errors import SliceError
from ag2c.index import build_index
from ag2c.slicer import compile_slice

from support import write_project


class EntrySlicerTests(unittest.TestCase):
    def test_path_selects_owner_knowledge_and_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, policy = write_project(Path(directory))
            build_index(manifest, policy)
            value = compile_slice(manifest, policy, path_specs=["app:src/worker/job.py"])
            card_ids = {card["id"] for card in value["cards"]}
            self.assertEqual(value["route"]["state"], "precise")
            self.assertTrue(
                {"constitution.project", "floor.worker", "floor.api", "knowledge.worker"}.issubset(card_ids)
            )
            self.assertEqual([checker["id"] for checker in value["check_plan"]], ["check.floor"])

    def test_contract_reverse_routes_boundary_ends_and_scenario(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, policy = write_project(Path(directory))
            build_index(manifest, policy)
            value = compile_slice(manifest, policy, contract_specs=["app:jobs.submit@1.0.0"])
            card_ids = {card["id"] for card in value["cards"]}
            self.assertTrue(
                {"boundary.jobs", "floor.api", "floor.worker", "scenario.jobs"}.issubset(card_ids)
            )
            self.assertEqual(
                {checker["id"] for checker in value["check_plan"]},
                {"check.floor", "check.boundary", "check.scenario"},
            )

    def test_unowned_planned_path_expands_target_floors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, policy = write_project(Path(directory))
            build_index(manifest, policy)
            value = compile_slice(manifest, policy, path_specs=["app:src/new_area/file.py"])
            self.assertEqual(value["route"]["state"], "conservative")
            card_ids = {card["id"] for card in value["cards"]}
            self.assertTrue({"floor.api", "floor.worker"}.issubset(card_ids))
            self.assertIn("unowned-entry:app:src/new_area/file.py", value["route"]["fallback_reasons"])

    def test_paths_covering_most_floors_expand_the_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, policy = write_project(Path(directory))
            build_index(manifest, policy)
            value = compile_slice(
                manifest,
                policy,
                path_specs=["app:src/api/service.py", "app:src/worker/job.py"],
            )
            self.assertEqual(value["route"]["state"], "conservative")
            self.assertIn("broad-change:app", value["route"]["fallback_reasons"])

    def test_goal_alone_cannot_select_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, policy = write_project(Path(directory))
            build_index(manifest, policy)
            with self.assertRaisesRegex(SliceError, "goal is advisory"):
                compile_slice(manifest, policy, goal="Improve the worker")
