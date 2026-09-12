import json
import tempfile
import unittest
from pathlib import Path

import bootstrap

from ag2c.errors import LedgerError
from ag2c.ledger import append_event, inspect_ledger, ledger_summary, verify_ledger


class LedgerTests(unittest.TestCase):
    def test_hash_chain_verifies_and_detects_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "ledger.jsonl"
            append_event(ledger, "route", {"state": "precise"})
            append_event(ledger, "check-run", {"status": "passed"})
            self.assertEqual(verify_ledger(ledger), [])
            errors, events = inspect_ledger(ledger)
            self.assertEqual([], errors)
            self.assertEqual(2, len(events))
            self.assertEqual(ledger_summary(ledger)["events"], 2)

            lines = ledger.read_text(encoding="utf-8").splitlines()
            first = json.loads(lines[0])
            first["payload"]["state"] = "tampered"
            lines[0] = json.dumps(first, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
            errors = verify_ledger(ledger)
            self.assertTrue(any("digest mismatch" in error for error in errors), errors)
            with self.assertRaisesRegex(LedgerError, "invalid ledger"):
                ledger_summary(ledger)


class SandboxTests(unittest.TestCase):
    def test_l2_to_l3_replay(self) -> None:
        from ag2c.errors import AG2CError
        from ag2c.sandbox import sandbox_replay
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "ledger.jsonl"
            empty = sandbox_replay(ledger, scenario="l2-to-l3")
            self.assertEqual(([], [], "ag2c.sandbox.v1", "l2-to-l3"), (empty["would_block"], empty["would_false_positive"], empty["schema"], empty["scenario"]))
            append_event(ledger, "task-completed", {"cards": ["knowledge.good"]})
            append_event(ledger, "verification-failed", {"cards": ["knowledge.bad"]})
            report = sandbox_replay(ledger, scenario="l2-to-l3")
            self.assertEqual(["knowledge.bad"], report["would_block"])
            self.assertEqual(["knowledge.bad"], report["would_false_positive"])
            self.assertEqual(["knowledge.good"], report["eligible"])
            self.assertTrue(report["read_only"])
            with self.assertRaises(AG2CError):
                sandbox_replay(ledger, scenario="nope")
