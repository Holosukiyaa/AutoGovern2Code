from __future__ import annotations

import unittest

import bootstrap  # noqa: F401

from ag2c_gui.graph import (
    KNOWLEDGE_TITLE_LIMIT,
    build_governance_graph,
    clip_knowledge_title,
    is_empty_leftover_parent,
    knowledge_lineage_index,
    knowledge_title,
)


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

    def test_graph_names_the_knowledge_card_that_covers_a_directory(self):
        graph = build_governance_graph(
            {
                "cards": [
                    _card("floor.src", "floor", "src", include=["src/**"]),
                    _card("knowledge.workbench", "knowledge", "当前画布", include=["src/frontend/**"]),
                ],
                "knowledge": [],
                "relations": [],
                "index": {"findings": []},
                "pending": {"items": []},
                "worktrees": [],
                "checkers": [],
                "census": {
                    "households": [
                        {
                            "id": "knowledge.workbench",
                            "kind": "knowledge",
                            "title": "当前画布",
                            "summary": "正牌前端",
                            "scopes": [{"includes": ["src/frontend/**"], "excludes": []}],
                            "checkers": ["check.frontend"],
                            "issues": [],
                            "jurisdiction": {
                                "capability": "frontend",
                                "implementation": "frontend.main",
                                "status": "current",
                            },
                            "freshness": "never",
                        }
                    ],
                    "directories": [
                        {
                            "target": "app",
                            "path": "src/frontend",
                            "files": ["src/frontend/main.tsx"],
                            "owners": ["knowledge.workbench"],
                            "unowned": 0,
                            "ambiguous": 0,
                        },
                        {
                            "target": "app",
                            "path": "prototypes/demo-free-layout",
                            "files": ["prototypes/demo-free-layout/src/app.tsx"],
                            "owners": [],
                            "unowned": 1,
                            "ambiguous": 0,
                        },
                    ],
                    "implementations": [],
                },
            }
        )
        frontend_file = next(node for node in graph["nodes"] if node["id"] == "file:app:src/frontend/main.tsx")
        self.assertIn("当前画布", frontend_file["coveredBy"])
        self.assertEqual("当前画布", frontend_file["coverageLabel"])
        hole_file = next(node for node in graph["nodes"] if node["id"] == "file:app:prototypes/demo-free-layout/src/app.tsx")
        self.assertEqual([], hole_file["coveredBy"])
        self.assertEqual("无知识卡覆盖", hole_file["coverageLabel"])
        card = next(node for node in graph["nodes"] if node["id"] == "knowledge.workbench")
        self.assertIn("src/frontend", card["coversDirectories"])
        self.assertEqual("current", frontend_file["role"])
        self.assertIn("src", frontend_file["floors"])
        self.assertEqual("unowned", hole_file["role"])
        self.assertNotIn("combos", graph)
        self.assertNotIn("edges", graph)

    def test_file_card_title_is_the_abstract_in_chinese_and_clips_to_20(self) -> None:
        long_title = "模块入口把 python -m ag2c 转给命令面解析"
        self.assertGreater(len(long_title), KNOWLEDGE_TITLE_LIMIT)
        clipped = clip_knowledge_title(long_title)
        self.assertEqual(KNOWLEDGE_TITLE_LIMIT, len(clipped))
        self.assertEqual(
            "模块入口转交 CLI",
            knowledge_title({"type": "knowledge", "title": "模块入口转交 CLI", "id": "knowledge.ag2c-dunder-main"}),
        )
        self.assertEqual(
            "src leftover parent",
            knowledge_title(
                {
                    "type": "knowledge",
                    "title": "src leftover parent",
                    "id": "knowledge.src",
                    "jurisdiction": {"span": "folder"},
                }
            ),
        )
        cli = _card(
            "knowledge.ag2c-cli",
            "knowledge",
            long_title,
            include=["src/ag2c/cli.py"],
            references=["src/ag2c/cli.py"],
            summary="命令面把参数交给 enrollment。真正的治理不在 cli.py。",
        )
        graph = build_governance_graph(
            {
                "cards": [cli],
                "knowledge": [],
                "relations": [],
                "index": {"findings": []},
                "pending": [],
                "worktrees": [],
                "checkers": [],
                "census": {
                    "households": [],
                    "directories": [
                        {
                            "target": "app",
                            "path": "src/ag2c",
                            "files": ["src/ag2c/cli.py"],
                            "owners": ["knowledge.ag2c-cli"],
                            "unowned": False,
                        }
                    ],
                },
            }
        )
        card_node = next(node for node in graph["nodes"] if node["id"] == "knowledge.ag2c-cli")
        file_node = next(node for node in graph["nodes"] if node["id"] == "file:app:src/ag2c/cli.py")
        self.assertEqual(clipped, card_node["title"])
        self.assertEqual(clipped, file_node["coverageLabel"])
        self.assertEqual([clipped], file_node["claimLabels"])
    def test_code_file_cards_are_not_document_tags(self) -> None:
        cli = _card("knowledge.ag2c-cli", "knowledge", "cli", include=["src/ag2c/cli.py"], references=["src/ag2c/cli.py"])
        readme = _card("knowledge.readme-md", "knowledge", "README.md", include=["README.md"], references=["README.md"])
        graph = build_governance_graph(
            {
                "cards": [cli, readme],
                "knowledge": [],
                "relations": [],
                "index": {"findings": []},
                "pending": [],
                "worktrees": [],
                "checkers": [],
            }
        )
        cli_node = next(node for node in graph["nodes"] if node["id"] == "knowledge.ag2c-cli")
        readme_node = next(node for node in graph["nodes"] if node["id"] == "knowledge.readme-md")
        self.assertEqual("current", cli_node["statusTag"])
        self.assertEqual("在册", cli_node["statusLabel"])
        self.assertEqual("document", readme_node["statusTag"])
        self.assertEqual("文档", readme_node["statusLabel"])
    def test_leftover_parent_does_not_own_carved_child_files(self) -> None:
        leftover = _card("knowledge.src", "knowledge", "src leftover parent", include=["src/**"])
        leftover["jurisdiction"] = {"span": "folder", "meaning": "none", "status": "current"}
        leftover["scopes"][0]["exclude"] = ["src/ag2c/**"]
        household = _card("knowledge.ag2c", "knowledge", "src/ag2c package", include=["src/ag2c/**"])
        household["jurisdiction"] = {"span": "file", "meaning": "named", "status": "current"}
        cli = _card(
            "knowledge.ag2c-cli",
            "knowledge",
            "cli",
            include=["src/ag2c/cli.py"],
            references=["src/ag2c/cli.py"],
        )
        graph = build_governance_graph(
            {
                "cards": [leftover, household, cli],
                "knowledge": [],
                "relations": [],
                "index": {"findings": []},
                "pending": [],
                "worktrees": [],
                "checkers": [],
                "census": {
                    "households": [
                        {
                            "id": "knowledge.src",
                            "kind": "knowledge",
                            "title": "src leftover parent",
                            "summary": "empty parent",
                            "identity": "exploring",
                            "scopes": [{"includes": ["src/**"], "excludes": ["src/ag2c/**"]}],
                            "checkers": [],
                            "issues": [],
                            "jurisdiction": leftover["jurisdiction"],
                            "freshness": "current",
                        },
                        {
                            "id": "knowledge.ag2c",
                            "kind": "knowledge",
                            "title": "src/ag2c package",
                            "summary": "engine",
                            "identity": "named",
                            "scopes": [{"includes": ["src/ag2c/**"], "excludes": []}],
                            "checkers": [],
                            "issues": [],
                            "jurisdiction": household["jurisdiction"],
                            "freshness": "current",
                        },
                    ],
                    "directories": [
                        {
                            "target": "app",
                            "path": "src/ag2c",
                            "files": ["src/ag2c/cli.py"],
                            "owners": ["knowledge.ag2c"],
                            "unowned": False,
                        }
                    ],
                },
            }
        )
        from ag2c_gui.tray_host import files_for_card, focus_card

        leftover_node = next(node for node in graph["nodes"] if node["id"] == "knowledge.src")
        ag2c_node = next(node for node in graph["nodes"] if node["id"] == "knowledge.ag2c")
        files = [(node["summary"], node) for node in graph["nodes"] if node.get("kind") == "file"]
        self.assertEqual([], files_for_card(files, leftover_node))
        self.assertEqual(["src/ag2c/cli.py"], files_for_card(files, ag2c_node))
        leftover_focus = focus_card(files, leftover_node)
        self.assertEqual(set(), leftover_focus["highlight_paths"])
        ag2c_focus = focus_card(files, ag2c_node)
        self.assertEqual({"src/ag2c/cli.py"}, ag2c_focus["highlight_paths"])

    def test_knowledge_lineage_index_nests_file_cards_under_the_room(self) -> None:
        household = _card("knowledge.ag2c", "knowledge", "src/ag2c package", include=["src/ag2c/**"], summary="room identity")
        household["jurisdiction"] = {"span": "file", "meaning": "named", "status": "current"}
        leftover = _card("knowledge.src", "knowledge", "src leftover parent", include=["src/**"], summary="empty parent")
        leftover["jurisdiction"] = {"span": "folder", "meaning": "none", "status": "current"}
        leftover["scopes"][0]["exclude"] = ["src/ag2c/**"]
        cli = _card(
            "knowledge.ag2c-cli",
            "knowledge",
            "cli",
            include=["src/ag2c/cli.py"],
            references=["src/ag2c/cli.py"],
            summary="argparse 命令面",
        )
        readme = _card("knowledge.readme-md", "knowledge", "README.md", include=["README.md"], references=["README.md"], summary="lead")
        index = knowledge_lineage_index(
            [household, leftover, cli, readme],
            selected_ids=["knowledge.ag2c", "knowledge.ag2c-cli"],
        )
        rooms = {item["id"]: item for item in index["rooms"]}
        self.assertIn("knowledge.ag2c", rooms)
        self.assertNotIn("knowledge.src", rooms)
        self.assertEqual(["src/ag2c/cli.py"], [item["path"] for item in rooms["knowledge.ag2c"]["files"]])
        self.assertIn("argparse 命令面", rooms["knowledge.ag2c"]["files"][0]["summary"])
        self.assertEqual([], index["documents"])

    def test_enrollment_placeholder_is_not_unreviewed_or_current(self) -> None:
        graph = build_governance_graph(
            {
                "cards": [
                    _card("floor.src", "floor", "src", include=["src/**"], checkers=["check.diff"]),
                    {
                        **_card("knowledge.src", "knowledge", "src exploring household", include=["src/**"]),
                        "jurisdiction": {
                            "capability": "src",
                            "implementation": "src.exploring",
                            "status": "current",
                            "meaning": "none",
                            "grain": "subtree",
                            "contract": "none",
                            "decider": "none",
                            "entrypoints": [],
                        },
                    },
                    _card("knowledge.readme-md", "knowledge", "README.md", references=["README.md"]),
                ],
                "knowledge": [
                    {"id": "knowledge.src", "status": "unknown", "reasons": ["census-review-required"], "jurisdiction": True},
                    {"id": "knowledge.readme-md", "status": "current", "source_status": "current", "reasons": []},
                ],
                "relations": [
                    {"source": "knowledge.src", "type": "explains", "target": "floor.src"},
                    {"source": "knowledge.readme-md", "type": "explains", "target": "floor.src"},
                ],
                "index": {"findings": []},
                "pending": {"items": []},
                "worktrees": [],
                "checkers": [{"id": "check.diff"}],
                "census": {
                    "households": [
                        {
                            "id": "knowledge.src",
                            "kind": "knowledge",
                            "title": "src exploring household",
                            "summary": "Declared exploring household",
                            "identity": "exploring",
                            "scopes": [{"includes": ["src/**"], "excludes": []}],
                            "checkers": [],
                            "issues": [],
                            "jurisdiction": {
                                "capability": "src",
                                "implementation": "src.exploring",
                                "status": "current",
                                "meaning": "none",
                            },
                            "freshness": "never",
                        }
                    ],
                    "directories": [
                        {"target": "app", "path": "src", "files": ["src/ag2c/graph.py"], "owners": ["knowledge.src"], "unowned": False}
                    ],
                },
            }
        )
        placeholder = next(node for node in graph["nodes"] if node["id"] == "knowledge.src")
        document = next(node for node in graph["nodes"] if node["id"] == "knowledge.readme-md")
        owned = next(node for node in graph["nodes"] if node["id"] == "file:app:src/ag2c/graph.py")
        self.assertEqual("placeholder", placeholder["statusTag"])
        self.assertEqual("占位", placeholder["statusLabel"])
        self.assertNotIn("unreviewed", placeholder["flags"])
        self.assertNotIn("exploring", placeholder["flags"])
        self.assertEqual("document", document["statusTag"])
        self.assertEqual("文档", document["statusLabel"])
        self.assertEqual(["占位 · src"], owned.get("claimLabels"))
    def test_operator_exploring_is_not_enrollment_placeholder(self) -> None:
        graph = build_governance_graph(
            {
                "cards": [_card("knowledge.shell", "knowledge", "Shell", include=["src/shell/**"])],
                "knowledge": [],
                "relations": [],
                "index": {"findings": []},
                "pending": {"items": []},
                "worktrees": [],
                "checkers": [],
                "census": {
                    "households": [
                        {
                            "id": "knowledge.shell",
                            "kind": "knowledge",
                            "title": "Shell",
                            "summary": "kept exploring",
                            "identity": "exploring",
                            "scopes": [{"includes": ["src/shell/**"], "excludes": []}],
                            "checkers": [],
                            "issues": [],
                            "jurisdiction": {
                                "capability": "shell",
                                "implementation": "shell.main",
                                "status": "current",
                                "meaning": "none",
                            },
                            "freshness": "never",
                        }
                    ],
                    "directories": [],
                },
            }
        )
        node = next(item for item in graph["nodes"] if item["id"] == "knowledge.shell")
        self.assertEqual("exploring", node["statusTag"])
        self.assertEqual("开工", node["statusLabel"])
        self.assertNotIn("placeholder", node["flags"])
        self.assertNotIn("unreviewed", node["flags"])


class EmptyLeftoverParentTests(unittest.TestCase):
    """is_empty_leftover_parent 的杀变异测试。 变异记录：graph.py 的 file_count > 0 → >= 0 曾存活（t17 变异金丝雀抓获， 看板常驻警情）——file_count=0 的合法占位卡必须判定为 True，否则谱系图 不再跳过它们。"""

    def _placeholder_card(self):
        return {
            "id": "knowledge.src",
            "jurisdiction": {
                "meaning": "none",
                "implementation": "rooms/src.exploring",
                "status": "current",
            },
            # 占位卡的标志：只持有排除护栏（src/** minus src/ag2c/** ...）
            "scopes": [{"target": "app", "include": ["src/**"], "exclude": ["src/ag2c/**"]}],
        }

    def test_zero_files_valid_placeholder_is_empty_leftover(self):
        self.assertTrue(is_empty_leftover_parent(self._placeholder_card(), file_count=0))

    def test_with_files_is_not_leftover(self):
        self.assertFalse(is_empty_leftover_parent(self._placeholder_card(), file_count=1))


class CanvasRemovalTests(unittest.TestCase):
    """The lineage canvas is dead; only the data layer (the AI's index) stays."""

    def test_graph_module_exposes_data_layer_only(self) -> None:
        import ag2c_gui.graph as graph

        for symbol in ("knowledge_lineage_index", "build_governance_graph", "knowledge_title", "lineage_heading", "lineage_ordinal_label"):
            self.assertTrue(callable(getattr(graph, symbol, None)), symbol)
        for symbol in ("build_lineage", "layout_lineage_view", "lineage_boxes_overlap", "lineage_step_overlaps", "lineage_visible_boxes", "lineage_uid", "lineage_card_width", "lineage_card_height", "assign_lineage_ordinals"):
            self.assertFalse(hasattr(graph, symbol), symbol)

    def test_tray_source_has_no_lineage_canvas_left(self) -> None:
        from pathlib import Path

        import ag2c_gui.imgui_tray as imgui_tray

        source = Path(imgui_tray.__file__).read_text(encoding="utf-8")
        for symbol in ("_gui_lineage", "_lineage_", "build_lineage", "layout_lineage_view", "imgui_node_editor", "谱系"):
            self.assertNotIn(symbol, source, symbol)

    def test_knowledge_lineage_index_still_feeds_the_agent(self) -> None:
        room = _card("knowledge.src", "knowledge", "src", include=["src/**"])
        room["jurisdiction"] = {"span": "folder"}
        index = knowledge_lineage_index([room])
        self.assertIn("rooms", index)
        self.assertIn("documents", index)
        self.assertEqual("knowledge.src", index["rooms"][0]["id"])
        self.assertEqual(["src"], index["rooms"][0]["include"])
