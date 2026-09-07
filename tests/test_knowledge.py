from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import bootstrap

from ag2c.index import build_index
from ag2c.knowledge import knowledge_status, sync_knowledge
from ag2c.ledger import read_events
from ag2c.slicer import compile_slice

from support import write_project


def knowledge_project(root: Path):
    manifest, policy = write_project(root)
    reference = root / "docs" / "worker.md"
    reference.parent.mkdir(parents=True)
    reference.write_text("Worker architecture\n", encoding="utf-8")
    policy_path = root / ".ag2c" / "policy.json"
    raw = json.loads(policy_path.read_text(encoding="utf-8"))
    worker = next(card for card in raw["cards"] if card["id"] == "knowledge.worker")
    worker["references"] = ["docs/worker.md"]
    policy_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    from ag2c.config import load_policy

    return manifest, load_policy(manifest), reference


class KnowledgeTests(unittest.TestCase):
    def test_unsynced_knowledge_is_unknown_without_changing_legacy_route(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, policy, _ = knowledge_project(Path(directory))
            build_index(manifest, policy)
            statuses = knowledge_status(manifest, policy)
            self.assertEqual(statuses[0]["status"], "unknown")
            entry_slice = compile_slice(manifest, policy, path_specs=["app:src/worker/job.py"])
            self.assertEqual(entry_slice["route"]["state"], "precise")
            knowledge = next(card for card in entry_slice["cards"] if card["id"] == "knowledge.worker")
            self.assertEqual(knowledge["freshness"]["status"], "unknown")

    def test_sync_marks_current_and_records_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, policy, _ = knowledge_project(Path(directory))
            result = sync_knowledge(
                manifest,
                policy,
                card_ids=["knowledge.worker"],
                actor="codex",
                reason="Reviewed worker implementation",
            )
            status = next(item for item in result["statuses"] if item["id"] == "knowledge.worker")
            self.assertEqual(status["status"], "current")
            self.assertEqual(status["assertion_status"], "current")
            self.assertEqual(status["assertions"][0]["text"], "Worker architecture")
            events = read_events(manifest.ledger_path)
            self.assertEqual(events[-1]["event_type"], "knowledge-sync")
            self.assertEqual(events[-1]["payload"]["actor"], "codex")

    def test_reference_change_marks_stale_and_expands_route(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, policy, reference = knowledge_project(Path(directory))
            build_index(manifest, policy)
            sync_knowledge(
                manifest,
                policy,
                card_ids=["knowledge.worker"],
                actor="codex",
                reason="Reviewed worker implementation",
            )
            reference.write_text("Worker architecture\nUpdated details\n", encoding="utf-8")
            status = next(item for item in knowledge_status(manifest, policy) if item["id"] == "knowledge.worker")
            self.assertEqual(status["status"], "stale")
            self.assertEqual(status["source_status"], "stale")
            self.assertEqual(status["assertion_status"], "current")
            entry_slice = compile_slice(manifest, policy, path_specs=["app:src/worker/job.py"])
            self.assertEqual(entry_slice["route"]["state"], "conservative")
            self.assertIn("stale-knowledge:knowledge.worker", entry_slice["route"]["fallback_reasons"])
            card_ids = {card["id"] for card in entry_slice["cards"]}
            self.assertIn("floor.api", card_ids)
            self.assertIn("floor.worker", card_ids)

    def test_rewritten_lead_marks_conflict_and_expands_route(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, policy, reference = knowledge_project(Path(directory))
            build_index(manifest, policy)
            sync_knowledge(
                manifest,
                policy,
                card_ids=["knowledge.worker"],
                actor="codex",
                reason="Reviewed worker implementation",
            )
            reference.write_text("Worker runtime rewritten\n", encoding="utf-8")
            status = next(item for item in knowledge_status(manifest, policy) if item["id"] == "knowledge.worker")
            self.assertEqual(status["status"], "conflict")
            self.assertEqual(status["source_status"], "stale")
            self.assertEqual(status["assertion_status"], "conflict")
            self.assertTrue(any(reason.startswith("assertion-changed:") for reason in status["reasons"]))
            entry_slice = compile_slice(manifest, policy, path_specs=["app:src/worker/job.py"])
            self.assertEqual(entry_slice["route"]["state"], "conservative")
            self.assertIn("conflict-knowledge:knowledge.worker", entry_slice["route"]["fallback_reasons"])
            card_ids = {card["id"] for card in entry_slice["cards"]}
            self.assertIn("floor.api", card_ids)
            self.assertIn("floor.worker", card_ids)


class CensusCacheKeyTests(unittest.TestCase):
    def test_census_and_renewal_state_bust_the_report_cache_key(self) -> None:
        from ag2c.households import _census_cache_key, census_path, renewal_path

        with tempfile.TemporaryDirectory() as directory:
            manifest, policy, _ = knowledge_project(Path(directory))
            key_before = _census_cache_key(manifest, policy)
            self.assertIsNotNone(key_before)
            census = census_path(manifest)
            census.parent.mkdir(parents=True, exist_ok=True)
            census.write_text('{"schema": "ag2c.census-state.v1", "records": []}\n', encoding="utf-8")
            key_after_census = _census_cache_key(manifest, policy)
            self.assertNotEqual(key_before, key_after_census)
            renewal = renewal_path(manifest)
            renewal.write_text('{"schema": "ag2c.renewal.v1", "cards": {}}\n', encoding="utf-8")
            key_after_renewal = _census_cache_key(manifest, policy)
            self.assertNotEqual(key_after_census, key_after_renewal)


if __name__ == "__main__":
    unittest.main()
