from __future__ import annotations

import unittest

import bootstrap  # noqa: F401

from ag2c.graph import build_governance_graph


def _card(card_id, kind, title, include=None, references=None, checkers=None, summary=""):
    return {
        "id": card_id,
        "type": kind,
        "title": title,
        "summary": summary,
        "scopes": [{"target": "app", "include": include or [], "exclude": [], "ownership": "primary"}],
        "checkers": checkers or [],
        "references": references or [],
    }


class GovernanceGraphTests(unittest.TestCase):
    def test_directory_without_knowledge_card_is_a_visible_unowned_leaf(self):
        graph = build_governance_graph(
            {
                "cards": [
                    _card("constitution.project", "constitution", "宪章"),
                    _card("floor.src", "floor", "src", include=["src/**"], checkers=["check.diff"]),
                    _card("knowledge.readme-md", "knowledge", "README", references=["README.md"]),
                ],
                "knowledge": [{"id": "knowledge.readme-md", "status": "current", "reasons": []}],
                "relations": [{"source": "knowledge.readme-md", "type": "explains", "target": "floor.src"}],
                "index": {"findings": []},
                "pending": {"items": []},
                "worktrees": [],
                "checkers": [{"id": "check.diff"}],
            }
        )
        gap = next(node for node in graph["nodes"] if node["id"] == "gap:src")
        self.assertEqual("gap", gap["kind"])
        self.assertIn("unowned", gap["flags"])
        self.assertTrue(graph["lazy"])
        self.assertGreaterEqual(graph["counts"]["unowned"], 1)
        self.assertTrue(any(node["id"] == "knowledge.readme-md" and node["kind"] == "knowledge" for node in graph["nodes"]))

    def test_stale_and_abandoned_knowledge_cannot_hide_in_current_counts(self):
        graph = build_governance_graph(
            {
                "cards": [
                    _card("knowledge.old-md", "knowledge", "旧文档", references=["OLD.md"]),
                    _card("knowledge.ghost-md", "knowledge", "幽灵", references=[]),
                ],
                "knowledge": [
                    {"id": "knowledge.old-md", "status": "stale", "source_status": "stale", "reasons": ["reference-digest-changed"]},
                    {"id": "knowledge.ghost-md", "status": "missing", "reasons": ["reference-missing"]},
                ],
                "relations": [],
                "index": {"findings": []},
                "pending": {"items": []},
                "worktrees": [],
                "checkers": [],
            }
        )
        stale = next(node for node in graph["nodes"] if node["id"] == "knowledge.old-md")
        abandoned = next(node for node in graph["nodes"] if node["id"] == "knowledge.ghost-md")
        self.assertIn("stale", stale["flags"])
        self.assertIn("abandoned", abandoned["flags"])
        self.assertEqual(0, graph["counts"]["current"])
        self.assertGreaterEqual(graph["counts"]["stale"], 1)
        self.assertGreaterEqual(graph["counts"]["abandoned"], 1)

    def test_ai_writing_in_a_hole_is_its_own_leaf(self):
        graph = build_governance_graph(
            {
                "cards": [_card("constitution.project", "constitution", "宪章")],
                "knowledge": [],
                "relations": [],
                "index": {"findings": []},
                "pending": {"items": []},
                "worktrees": [
                    {
                        "id": "task-lazy",
                        "goal": "随便加一点",
                        "state": "active",
                        "paths": ["app:src/secret"],
                    }
                ],
                "checkers": [],
            }
        )
        work = next(node for node in graph["nodes"] if node["kind"] == "work")
        self.assertIn("writing", work["flags"])
        self.assertIn("unowned", work["flags"])
        self.assertGreaterEqual(graph["counts"]["writing"], 1)

    def test_uncovered_finding_and_missing_product_check_become_gaps(self):
        graph = build_governance_graph(
            {
                "cards": [_card("constitution.project", "constitution", "宪章")],
                "knowledge": [],
                "relations": [],
                "index": {
                    "findings": [
                        {
                            "finding_type": "scope-uncovered",
                            "artifact_id": "app:orphan/file.py",
                            "message": "No primary floor owns app:orphan/file.py",
                        }
                    ]
                },
                "pending": {"items": [{"kind": "undeclared-product", "action": "declare-product-checks", "title": "还没有产品验收"}]},
                "worktrees": [],
                "checkers": [],
            }
        )
        self.assertTrue(any(node["id"] == "gap:orphan" and "unowned" in node["flags"] for node in graph["nodes"]))
        self.assertTrue(any(node["id"] == "gap:product" and "undeclared" in node["flags"] for node in graph["nodes"]))
        self.assertIn("无主", graph["headline"])
        self.assertIn("未验收", graph["headline"])

    def test_current_knowledge_leaf_is_not_marked_lazy(self):
        graph = build_governance_graph(
            {
                "cards": [
                    _card("constitution.project", "constitution", "宪章"),
                    _card("floor.src", "floor", "src", include=["src/**"]),
                    _card("knowledge.src", "knowledge", "源码", references=["src/__init__.py"], include=["src/**"]),
                ],
                "knowledge": [{"id": "knowledge.src", "status": "current", "source_status": "current", "reasons": []}],
                "relations": [{"source": "knowledge.src", "type": "explains", "target": "floor.src"}],
                "index": {"findings": []},
                "pending": {"items": []},
                "worktrees": [],
                "checkers": [{"id": "check.diff"}],
            }
        )
        leaf = next(node for node in graph["nodes"] if node["id"] == "knowledge.src")
        self.assertEqual("knowledge", leaf["kind"])
        self.assertFalse(leaf["lazy"])
        self.assertFalse(any(node["id"] == "gap:src" for node in graph["nodes"]))
