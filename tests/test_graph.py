from __future__ import annotations

import unittest

import bootstrap  # noqa: F401

from ag2c.graph import (
    KNOWLEDGE_TITLE_LIMIT,
    LINEAGE_CARD_H,
    LINEAGE_CARD_MAX_W,
    LINEAGE_CARD_MIN_W,
    LINEAGE_COLLAPSED_H,
    LINEAGE_COLLAPSED_W,
    LINEAGE_MODULE_HEADER,
    LINEAGE_MODULE_PAD,
    LINEAGE_ORIGIN_X,
    LINEAGE_PROJECT_ID,
    build_governance_graph,
    build_lineage,
    clip_knowledge_title,
    knowledge_lineage_index,
    knowledge_title,
    layout_lineage_view,
    lineage_boxes_overlap,
    lineage_card_width,
    lineage_ordinal,
    lineage_related_ids,
    lineage_step_overlaps,
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

    def test_lineage_nests_file_span_cards_under_the_directory_household(self) -> None:
        household = _card("knowledge.ag2c", "knowledge", "src/ag2c package", include=["src/ag2c/**"])
        household["jurisdiction"] = {"span": "file", "meaning": "named", "status": "current", "capability": "ag2c", "implementation": "ag2c.main"}
        household["scopes"][0]["exclude"] = ["src/ag2c/skills/**"]
        cli = _card("knowledge.ag2c-cli", "knowledge", "cli", include=["src/ag2c/cli.py"], references=["src/ag2c/cli.py"])
        tray = _card(
            "knowledge.ag2c-imgui-tray",
            "knowledge",
            "Hello ImGui tray",
            include=["src/ag2c/imgui_tray.py"],
            references=["src/ag2c/imgui_tray.py"],
        )
        sibling = _card("knowledge.src", "knowledge", "src leftover", include=["src/**"])
        sibling["jurisdiction"] = {"span": "folder", "meaning": "none", "status": "current"}
        lineage = build_lineage(
            {
                "project": {"name": "AutoGovern2Code"},
                "cards": [
                    _card("constitution.project", "constitution", "宪章"),
                    _card("floor.src", "floor", "src", include=["src/**"]),
                    household,
                    cli,
                    tray,
                    sibling,
                ],
                "relations": [
                    {"source": "knowledge.ag2c", "type": "explains", "target": "floor.src"},
                    {"source": "knowledge.ag2c-cli", "type": "explains", "target": "floor.src"},
                    {"source": "knowledge.ag2c-imgui-tray", "type": "explains", "target": "floor.src"},
                    {"source": "knowledge.src", "type": "explains", "target": "floor.src"},
                ],
                "graph": {"nodes": []},
            }
        )
        cli_node = next(node for node in lineage["nodes"] if node["id"] == "knowledge.ag2c-cli")
        tray_node = next(node for node in lineage["nodes"] if node["id"] == "knowledge.ag2c-imgui-tray")
        household_node = next(node for node in lineage["nodes"] if node["id"] == "knowledge.ag2c")
        leftover = next(node for node in lineage["nodes"] if node["id"] == "knowledge.src")
        self.assertEqual("knowledge.ag2c@floor.src", cli_node["parent"])
        self.assertEqual("knowledge.ag2c@floor.src", tray_node["parent"])
        self.assertEqual(3, cli_node["layer"])
        self.assertEqual("floor.src", household_node["parent"])
        self.assertEqual(2, household_node["layer"])
        self.assertEqual("floor.src", leftover["parent"])
        self.assertTrue(household_node.get("nested"))
        self.assertEqual(2, len(household_node.get("cards") or []))
        src = next(node for node in lineage["nodes"] if node["visual_id"] == "floor.src")
        self.assertEqual({"knowledge.ag2c", "knowledge.src"}, {item["id"] for item in src.get("cards") or []})
        self.assertTrue(cli_node.get("hidden"))
        nodes = [dict(item) for item in lineage["nodes"]]
        layout_lineage_view(nodes, {LINEAGE_PROJECT_ID, "floor.src"})
        hidden_cli = next(item for item in nodes if item["id"] == "knowledge.ag2c-cli")
        self.assertTrue(hidden_cli.get("hidden"))
        layout_lineage_view(nodes, {LINEAGE_PROJECT_ID, "floor.src", "knowledge.ag2c@floor.src"})
        shown_cli = next(item for item in nodes if item["id"] == "knowledge.ag2c-cli")
        shown_house = next(item for item in nodes if item["visual_id"] == "knowledge.ag2c@floor.src")
        src_box = next(item for item in nodes if item["visual_id"] == "floor.src")
        self.assertFalse(shown_cli.get("hidden"))
        self.assertEqual("knowledge.ag2c@floor.src", shown_cli["parent"])
        self.assertGreater(shown_cli["x"], shown_house["x"] + shown_house["width"])
        self.assertGreater(shown_cli["x"], src_box["x"] + src_box["width"])
        leftover_node = next(item for item in nodes if item["id"] == "knowledge.src")
        self.assertLess(leftover_node["x"] + leftover_node["width"], shown_cli["x"])
        self.assertGreaterEqual(lineage_ordinal(shown_cli), 1)
        self.assertEqual("cli", shown_cli["title"])
        self.assertNotIn("abstract", shown_cli)
        hull = shown_house.get("outward_hull")
        self.assertIsInstance(hull, dict)
        self.assertGreater(float(hull["x"]), shown_house["x"] + shown_house["width"])
        self.assertGreaterEqual(shown_cli["x"], float(hull["x"]))
        self.assertLessEqual(shown_cli["x"] + shown_cli["width"], float(hull["x"]) + float(hull["width"]))
        self.assertGreaterEqual(shown_cli["y"], float(hull["y"]))
        self.assertLessEqual(shown_cli["y"] + shown_cli["height"], float(hull["y"]) + float(hull["height"]))
        collapsed = [dict(item) for item in lineage["nodes"]]
        layout_lineage_view(collapsed, {LINEAGE_PROJECT_ID, "floor.src"})
        folded = next(item for item in collapsed if item["visual_id"] == "knowledge.ag2c@floor.src")
        self.assertFalse(folded.get("outward_hull"))
        graph = build_governance_graph(
            {
                "cards": [household, cli, tray],
                "knowledge": [],
                "relations": [],
                "index": {"findings": []},
                "pending": [],
                "worktrees": [],
                "checkers": [],
            }
        )
        cli_graph = next(node for node in graph["nodes"] if node["id"] == "knowledge.ag2c-cli")
        self.assertEqual("knowledge.ag2c", cli_graph.get("parentCard"))
        self.assertNotEqual("document", cli_graph["statusTag"])
        self.assertNotIn("document", cli_graph.get("flags") or [])
        household_lineage = next(node for node in lineage["nodes"] if node["id"] == "knowledge.ag2c")
        leftover_lineage = next(node for node in lineage["nodes"] if node["id"] == "knowledge.src")
        self.assertEqual("file", household_lineage.get("span"))
        self.assertEqual("一文件一张", household_lineage.get("spanLabel"))
        self.assertEqual("folder", leftover_lineage.get("span"))

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
        lineage = build_lineage(
            {
                "project": {"name": "AutoGovern2Code"},
                "cards": [
                    _card("constitution.project", "constitution", "宪章"),
                    _card("floor.src", "floor", "src", include=["src/**"]),
                    cli,
                ],
                "relations": [{"source": "knowledge.ag2c-cli", "type": "explains", "target": "floor.src"}],
                "graph": {"nodes": []},
            }
        )
        shown = next(node for node in lineage["nodes"] if node["id"] == "knowledge.ag2c-cli")
        self.assertEqual(clipped, shown["title"])
        self.assertNotIn("abstract", shown)

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
        lineage = build_lineage(
            {
                "project": {"name": "AutoGovern2Code"},
                "cards": [
                    _card("floor.src", "floor", "src", include=["src/**"]),
                    cli,
                    readme,
                ],
                "relations": [
                    {"source": "knowledge.ag2c-cli", "type": "explains", "target": "floor.src"},
                    {"source": "knowledge.readme-md", "type": "explains", "target": "floor.src"},
                ],
                "graph": {"nodes": []},
            }
        )
        cli_lineage = next(node for node in lineage["nodes"] if node["id"] == "knowledge.ag2c-cli")
        readme_lineage = next(node for node in lineage["nodes"] if node["id"] == "knowledge.readme-md")
        self.assertNotEqual("文档", cli_lineage["status"])
        self.assertEqual("文档", readme_lineage["status"])

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
        from ag2c.tray_host import files_for_card, focus_card

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

    def test_lineage_is_project_modules_and_knowledge_cards(self) -> None:
        lineage = build_lineage(
            {
                "project": {"name": "CartridgeFlow"},
                "cards": [
                    _card("constitution.project", "constitution", "宪章", summary="项目总则"),
                    _card("floor.src", "floor", "src", include=["src/**"]),
                    _card("floor.front", "floor", "frontend", include=["src/frontend/**"]),
                    _card("knowledge.src", "knowledge", "源码", include=["src/**"]),
                    _card("knowledge.old", "knowledge", "旧卡"),
                ],
                "relations": [
                    {"source": "constitution.project", "type": "governs", "target": "floor.src"},
                    {"source": "knowledge.src", "type": "explains", "target": "floor.src"},
                    {"source": "knowledge.old", "type": "replaced_by", "target": "knowledge.src"},
                ],
                "graph": {"nodes": []},
            },
            project_name="CartridgeFlow",
        )
        kinds = {node["visual_id"]: node["kind"] for node in lineage["nodes"]}
        self.assertEqual("project", kinds["project:root"])
        self.assertEqual("module", kinds["floor.src"])
        self.assertEqual("knowledge", kinds["knowledge.src@floor.src"])
        project = next(node for node in lineage["nodes"] if node["kind"] == "project")
        self.assertEqual("CartridgeFlow", project["title"])
        self.assertIn("宪章", project["status"])
        src = next(node for node in lineage["nodes"] if node["visual_id"] == "floor.src")
        self.assertEqual("src", src["title"])
        self.assertEqual("1 张知识卡", src["status"])
        front = next(node for node in lineage["nodes"] if node["visual_id"] == "floor.front")
        self.assertEqual("src/frontend", front["title"])
        self.assertTrue(front["empty"])
        old = next(node for node in lineage["nodes"] if node["id"] == "knowledge.old")
        self.assertEqual("module:ungrouped", old["parent"])
        self.assertEqual("源码", old["replaced_by"])
        self.assertFalse(any(node["kind"] == "file" for node in lineage["nodes"]))
        self.assertFalse(any(node["kind"] in {"constitution", "floor"} for node in lineage["nodes"]))
        edges = {(item["source"], item["type"], item["target"]) for item in lineage["edges"]}
        self.assertIn(("project:root", "module", "floor.src"), edges)
        self.assertFalse(any(item.get("type") == "card" for item in lineage["edges"]))
        self.assertTrue(src.get("group"))
        self.assertEqual(1, len(src.get("cards") or []))
        related = lineage_related_ids(lineage, "knowledge.src")
        self.assertIn("knowledge.src@floor.src", related)
        self.assertIn("floor.src", related)

    def test_lineage_combo_boxes_do_not_overlap(self) -> None:
        cards = [
            _card("constitution.project", "constitution", "宪章"),
            _card("floor.src", "floor", "src", include=["src/**"]),
            _card("floor.front", "floor", "frontend", include=["src/frontend/**"]),
            _card("floor.back", "floor", "backend", include=["src/backend/**"]),
        ]
        relations = []
        for index in range(5):
            card_id = f"knowledge.n{index}"
            cards.append(_card(card_id, "knowledge", f"卡 {index}", include=[f"src/n{index}.py"]))
            relations.append({"source": card_id, "type": "explains", "target": "floor.src"})
        cards.append(_card("knowledge.front", "knowledge", "前端卡", include=["src/frontend/a.ts"]))
        relations.append({"source": "knowledge.front", "type": "explains", "target": "floor.front"})
        lineage = build_lineage({"project": {"name": "Demo"}, "cards": cards, "relations": relations, "graph": {"nodes": []}})
        modules = [node for node in lineage["nodes"] if node["kind"] == "module"]
        project = next(node for node in lineage["nodes"] if node["kind"] == "project")
        self.assertGreaterEqual(len(modules), 3)
        src = next(node for node in modules if node["visual_id"] == "floor.src")
        self.assertEqual("5 张知识卡", src["status"])
        self.assertEqual(5, len(src["cards"]))
        for left_index, left in enumerate(modules):
            self.assertFalse(lineage_boxes_overlap(project, left, gap=8.0))
            for right in modules[left_index + 1 :]:
                self.assertFalse(lineage_boxes_overlap(left, right, gap=8.0), (left["title"], right["title"]))
        kids = [node for node in lineage["nodes"] if node.get("parent") == "floor.src"]
        kids.sort(key=lambda item: float(item["y"]))
        self.assertEqual(5, len(kids))
        for child in kids:
            self.assertGreaterEqual(child["x"], src["x"])
            self.assertGreaterEqual(child["y"], src["y"])
            self.assertLessEqual(child["x"] + child["width"], src["x"] + src["width"])
            self.assertLessEqual(child["y"] + child["height"], src["y"] + src["height"])
        card_xs = {float(child["x"]) for child in kids}
        self.assertEqual(1, len(card_xs))
        for index in range(1, len(kids)):
            gap = float(kids[index]["y"]) - (float(kids[index - 1]["y"]) + float(kids[index - 1]["height"]))
            self.assertAlmostEqual(10.0, gap, delta=0.5)
        for left_index, left in enumerate(kids):
            for right in kids[left_index + 1 :]:
                self.assertFalse(lineage_boxes_overlap(left, right, gap=4.0))
        module_xs = {float(node["x"]) for node in modules}
        self.assertEqual(1, len(module_xs))
        self.assertLessEqual(float(project["x"]) + float(project["width"]) + 8.0, min(module_xs))
        stack_top = min(float(node["y"]) for node in modules)
        stack_bot = max(float(node["y"]) + float(node["height"]) for node in modules)
        self.assertAlmostEqual(
            float(project["y"]) + float(project["height"]) / 2.0,
            (stack_top + stack_bot) / 2.0,
            delta=2.0,
        )

    def test_lineage_view_defaults_to_collapsed_project(self) -> None:
        lineage = build_lineage(
            {
                "project": {"name": "Demo"},
                "cards": [
                    _card("constitution.project", "constitution", "宪章"),
                    _card("floor.src", "floor", "src", include=["src/**"]),
                    _card("knowledge.src", "knowledge", "源码", include=["src/**"]),
                ],
                "relations": [{"source": "knowledge.src", "type": "explains", "target": "floor.src"}],
                "graph": {"nodes": []},
            }
        )
        nodes = [dict(item) for item in lineage["nodes"]]
        layout_lineage_view(nodes, set())
        hidden = {item["kind"]: item.get("hidden") for item in nodes}
        self.assertFalse(next(item for item in nodes if item["kind"] == "project").get("hidden"))
        self.assertTrue(all(item.get("hidden") for item in nodes if item["kind"] != "project"))
        layout_lineage_view(nodes, {LINEAGE_PROJECT_ID})
        modules = [item for item in nodes if item["kind"] == "module"]
        self.assertTrue(all(not item.get("hidden") for item in modules))
        self.assertTrue(all(item.get("hidden") for item in nodes if item["kind"] == "knowledge"))
        src = next(item for item in modules if item["visual_id"] == "floor.src")
        layout_lineage_view(nodes, {LINEAGE_PROJECT_ID, "floor.src"})
        cards = [item for item in nodes if item.get("parent") == "floor.src"]
        self.assertTrue(all(not item.get("hidden") for item in cards))
        self.assertEqual(1, len({float(item["x"]) for item in cards}))

    def test_lineage_expand_steps_do_not_overlap(self) -> None:
        cards = [
            _card("constitution.project", "constitution", "宪章"),
            _card("floor.src", "floor", "src", include=["src/**"]),
            _card("floor.front", "floor", "frontend", include=["src/frontend/**"]),
            _card("floor.back", "floor", "backend", include=["src/backend/**"]),
        ]
        relations = []
        for index in range(5):
            card_id = f"knowledge.n{index}"
            cards.append(_card(card_id, "knowledge", f"卡 {index}", include=[f"src/n{index}.py"]))
            relations.append({"source": card_id, "type": "explains", "target": "floor.src"})
        cards.append(_card("knowledge.front", "knowledge", "前端卡", include=["src/frontend/a.ts"]))
        relations.append({"source": "knowledge.front", "type": "explains", "target": "floor.front"})
        lineage = build_lineage({"project": {"name": "Demo"}, "cards": cards, "relations": relations, "graph": {"nodes": []}})
        steps = [
            set(),
            {LINEAGE_PROJECT_ID},
            {LINEAGE_PROJECT_ID, "floor.src"},
            {LINEAGE_PROJECT_ID, "floor.src", "floor.front"},
            {LINEAGE_PROJECT_ID, "floor.src", "floor.front", "floor.back"},
        ]
        for expanded in steps:
            nodes = [dict(item) for item in lineage["nodes"]]
            hits = lineage_step_overlaps(nodes, expanded, gap=8.0)
            self.assertEqual([], hits, expanded)

    def test_expanded_combo_wraps_cards_not_a_title_strip(self) -> None:
        cards = [
            _card("constitution.project", "constitution", "宪章"),
            _card("floor.src", "floor", "src", include=["src/**"]),
            _card("floor.front", "floor", "frontend", include=["src/frontend/**"]),
        ]
        relations = []
        for index in range(5):
            card_id = f"knowledge.n{index}"
            cards.append(_card(card_id, "knowledge", f"卡 {index}", include=[f"src/n{index}.py"]))
            relations.append({"source": card_id, "type": "explains", "target": "floor.src"})
        lineage = build_lineage({"project": {"name": "Demo"}, "cards": cards, "relations": relations, "graph": {"nodes": []}})
        self.assertLessEqual(LINEAGE_MODULE_HEADER, 36.0)
        nodes = [dict(item) for item in lineage["nodes"]]
        layout_lineage_view(nodes, {LINEAGE_PROJECT_ID})
        src = next(item for item in nodes if item["visual_id"] == "floor.src")
        self.assertEqual(LINEAGE_COLLAPSED_W, src["width"])
        self.assertEqual(LINEAGE_COLLAPSED_H, src["height"])
        self.assertTrue(all(item.get("hidden") for item in nodes if item.get("parent") == "floor.src"))
        layout_lineage_view(nodes, {LINEAGE_PROJECT_ID, "floor.src"})
        src = next(item for item in nodes if item["visual_id"] == "floor.src")
        kids = [item for item in nodes if item.get("parent") == "floor.src"]
        self.assertGreater(src["height"], LINEAGE_MODULE_HEADER + LINEAGE_CARD_H)
        self.assertGreater(src["height"], LINEAGE_COLLAPSED_H)
        kids.sort(key=lambda item: float(item["y"]))
        for child in kids:
            self.assertFalse(child.get("hidden"))
            self.assertGreaterEqual(child["x"], src["x"])
            self.assertLessEqual(child["x"] + child["width"], src["x"] + src["width"])
            self.assertLessEqual(child["y"] + child["height"], src["y"] + src["height"])
            self.assertGreater(child["y"], src["y"] + 8.0)
        self.assertAlmostEqual(float(kids[0]["y"]), src["y"] + LINEAGE_MODULE_HEADER, delta=0.5)
        front = next(item for item in nodes if item["visual_id"] == "floor.front")
        self.assertEqual(LINEAGE_COLLAPSED_H, front["height"])
        self.assertEqual(LINEAGE_COLLAPSED_W, front["width"])
        self.assertFalse(lineage_boxes_overlap(src, front, gap=8.0))

    def test_lineage_card_width_is_elastic_and_clamped(self) -> None:
        short = {"title": "短", "status": "在册", "replaced_by": ""}
        long_title = {
            "title": "旧原型：FlowGram 自由布局示例还要更长一些直到超过上限",
            "status": "开工",
            "replaced_by": "",
        }
        replaced = {
            "title": "旧原型：FlowGram 自由布局示例",
            "status": "开工",
            "replaced_by": "正式工作台与遗留画布分支",
        }
        self.assertEqual(LINEAGE_CARD_MIN_W, lineage_card_width(short))
        self.assertEqual(LINEAGE_CARD_MAX_W, lineage_card_width(long_title))
        mid = lineage_card_width(replaced)
        self.assertGreater(mid, LINEAGE_CARD_MIN_W)
        self.assertLessEqual(mid, LINEAGE_CARD_MAX_W)

    def test_expanded_combo_cards_share_one_elastic_width(self) -> None:
        cards = [
            _card("constitution.project", "constitution", "宪章"),
            _card("floor.proto", "floor", "prototypes", include=["prototypes/**"]),
            _card("knowledge.short", "knowledge", "短卡", include=["prototypes/a.py"]),
            _card("knowledge.long", "knowledge", "旧原型：FlowGram 自由布局示例", include=["prototypes/b.py"]),
        ]
        relations = [
            {"source": "knowledge.short", "type": "explains", "target": "floor.proto"},
            {"source": "knowledge.long", "type": "explains", "target": "floor.proto"},
        ]
        lineage = build_lineage({"project": {"name": "Demo"}, "cards": cards, "relations": relations, "graph": {"nodes": []}})
        nodes = [dict(item) for item in lineage["nodes"]]
        layout_lineage_view(nodes, {LINEAGE_PROJECT_ID, "floor.proto"})
        project = next(item for item in nodes if item["kind"] == "project")
        self.assertEqual(LINEAGE_ORIGIN_X, project["x"])
        kids = [item for item in nodes if item.get("parent") == "floor.proto"]
        self.assertEqual(2, len(kids))
        widths = {float(item["width"]) for item in kids}
        self.assertEqual(1, len(widths))
        width = next(iter(widths))
        self.assertGreater(width, LINEAGE_CARD_MIN_W)
        self.assertLessEqual(width, LINEAGE_CARD_MAX_W)
        proto = next(item for item in nodes if item["visual_id"] == "floor.proto")
        self.assertGreaterEqual(proto["width"], width + LINEAGE_MODULE_PAD * 2)
        for child in kids:
            self.assertLessEqual(child["x"] + child["width"], proto["x"] + proto["width"])

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
        lineage = build_lineage(
            {
                "project": {"name": "AutoGovern2Code-main"},
                "cards": [
                    _card("floor.src", "floor", "src", include=["src/**"]),
                    {
                        **_card("knowledge.src", "knowledge", "src exploring household", include=["src/**"]),
                        "jurisdiction": {
                            "capability": "src",
                            "implementation": "src.exploring",
                            "meaning": "none",
                            "status": "current",
                        },
                    },
                    _card("knowledge.readme-md", "knowledge", "README.md", references=["README.md"]),
                ],
                "relations": [
                    {"source": "knowledge.src", "type": "explains", "target": "floor.src"},
                    {"source": "knowledge.readme-md", "type": "explains", "target": "floor.src"},
                ],
                "graph": {"nodes": graph["nodes"]},
            }
        )
        module = next(node for node in lineage["nodes"] if node["visual_id"] == "floor.src")
        self.assertEqual("placeholder", module["statusTag"])
        self.assertEqual("占位", module["status"])
        readme = next(node for node in lineage["nodes"] if node["id"] == "knowledge.readme-md")
        self.assertEqual("文档", readme["status"])
        house = next(node for node in lineage["nodes"] if node["id"] == "knowledge.src")
        self.assertEqual("占位", house["status"])

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
