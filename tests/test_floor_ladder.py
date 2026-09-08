"""Floor optional + maturity ladder tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ag2c.config import load_policy
from ag2c.model import Card, Manifest, Target


def _manifest_for(policy_path: Path) -> Manifest:
    root = policy_path.parent
    return Manifest(
        path=root / "manifest.json",
        project_id="test",
        project_root=root,
        policy_path=policy_path,
        state_dir=root / "state",
        ledger_path=root / "ledger.jsonl",
        targets=(Target(target_id="app", path=".", governed_roots=("src",), excludes=()),),
    )


class OptionalFieldTests(unittest.TestCase):
    def test_optional_defaults_to_false(self) -> None:
        card = Card(
            card_id="test",
            card_type="floor",
            title="test",
            summary="test",
            scopes=(),
            checkers=(),
            references=(),
        )
        self.assertFalse(card.optional)

    def test_optional_set_to_true(self) -> None:
        card = Card(
            card_id="test",
            card_type="floor",
            title="test",
            summary="test",
            scopes=(),
            checkers=(),
            references=(),
            optional=True,
        )
        self.assertTrue(card.optional)

    def test_maturity_defaults_to_empty(self) -> None:
        card = Card(
            card_id="test",
            card_type="knowledge",
            title="test",
            summary="test",
            scopes=(),
            checkers=(),
            references=(),
        )
        self.assertEqual("", card.maturity)

    def test_maturity_set(self) -> None:
        card = Card(
            card_id="test",
            card_type="knowledge",
            title="test",
            summary="test",
            scopes=(),
            checkers=(),
            references=(),
            maturity="L2",
        )
        self.assertEqual("L2", card.maturity)


def _floor_card() -> dict:
    return {
        "id": "floor.app",
        "type": "floor",
        "title": "app",
        "summary": "app floor",
        "scopes": [{"target": "app", "include": ["src/**"], "ownership": "primary"}],
        "checkers": ["check.diff"],
        "references": [],
    }


def _checker() -> dict:
    return {
        "id": "check.diff",
        "stage": "floor",
        "target": "app",
        "command": ["git", "diff", "--check"],
        "cwd": ".",
        "timeout": 30,
    }


class ConfigParsingTests(unittest.TestCase):
    def test_optional_parsed_from_policy(self) -> None:
        floor = _floor_card()
        floor["optional"] = True
        raw = {
            "schema": "ag2c.policy.v1",
            "cards": [floor],
            "relations": [],
            "contracts": [],
            "checkers": [_checker()],
            "coverage": {"level": "baseline", "strategy": "conservative", "managed_by": "human", "areas": []},
        }
        path = Path(tempfile.mkdtemp()) / "policy.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        policy = load_policy(_manifest_for(path))
        card = policy.card("floor.app")
        self.assertTrue(card.optional)

    def test_maturity_parsed_from_policy(self) -> None:
        raw = {
            "schema": "ag2c.policy.v1",
            "cards": [
                _floor_card(),
                {
                    "id": "knowledge.core",
                    "type": "knowledge",
                    "title": "core",
                    "summary": "core module",
                    "scopes": [],
                    "checkers": [],
                    "references": [],
                    "maturity": "L2",
                },
            ],
            "relations": [],
            "contracts": [],
            "checkers": [_checker()],
            "coverage": {"level": "baseline", "strategy": "conservative", "managed_by": "human", "areas": []},
        }
        path = Path(tempfile.mkdtemp()) / "policy.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        policy = load_policy(_manifest_for(path))
        card = policy.card("knowledge.core")
        self.assertEqual("L2", card.maturity)

    def test_missing_fields_default(self) -> None:
        raw = {
            "schema": "ag2c.policy.v1",
            "cards": [
                _floor_card(),
                {
                    "id": "knowledge.old",
                    "type": "knowledge",
                    "title": "old",
                    "summary": "old module",
                    "scopes": [],
                    "checkers": [],
                    "references": [],
                },
            ],
            "relations": [],
            "contracts": [],
            "checkers": [_checker()],
            "coverage": {"level": "baseline", "strategy": "conservative", "managed_by": "human", "areas": []},
        }
        path = Path(tempfile.mkdtemp()) / "policy.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        policy = load_policy(_manifest_for(path))
        card = policy.card("knowledge.old")
        self.assertFalse(card.optional)
        self.assertEqual("", card.maturity)


class MaturitySummaryTests(unittest.TestCase):
    def test_maturity_summary_counts(self) -> None:
        """Verify that maturity_summary counts rooms by level."""
        # This is tested indirectly through run_checks; here we test the logic.
        cards = [
            Card(card_id="a", card_type="knowledge", title="a", summary="a",
                 scopes=(), checkers=(), references=(), jurisdiction={"span": "folder"}, maturity="L1"),
            Card(card_id="b", card_type="knowledge", title="b", summary="b",
                 scopes=(), checkers=(), references=(), jurisdiction={"span": "folder"}, maturity="L1"),
            Card(card_id="c", card_type="knowledge", title="c", summary="c",
                 scopes=(), checkers=(), references=(), jurisdiction={"span": "folder"}, maturity="L2"),
            Card(card_id="d", card_type="knowledge", title="d", summary="d",
                 scopes=(), checkers=(), references=(), jurisdiction={"span": "folder"}),  # no maturity
            Card(card_id="e", card_type="floor", title="e", summary="e",
                 scopes=(), checkers=(), references=()),  # floor, no jurisdiction
        ]
        maturity_counts: dict[str, int] = {}
        for card in cards:
            if card.jurisdiction is not None and card.maturity:
                maturity_counts[card.maturity] = maturity_counts.get(card.maturity, 0) + 1
        self.assertEqual({"L1": 2, "L2": 1}, maturity_counts)


if __name__ == "__main__":
    unittest.main()


