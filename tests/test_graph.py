from __future__ import annotations

import unittest

import bootstrap  # noqa: F401

from ag2c_gui.graph import (
    KNOWLEDGE_TITLE_LIMIT,
    LINEAGE_CARD_H,
    LINEAGE_CARD_MAX_W,
    LINEAGE_CARD_MIN_W,
    LINEAGE_CARD_GAP_Y,
    LINEAGE_COLLAPSED_H,
    LINEAGE_COLLAPSED_W,
    LINEAGE_MODULE_HEADER,
    LINEAGE_MODULE_PAD,
    LINEAGE_ORIGIN_X,
    LINEAGE_TREE_INDENT,
    LINEAGE_TREE_ROOT_W,
    lineage_card_height,
    LINEAGE_PROJECT_ID,
    build_governance_graph,
    build_lineage,
    clip_knowledge_title,
    knowledge_lineage_index,
    knowledge_title,
    layout_lineage_view,
    lineage_boxes_overlap,
    lineage_card_width,
    lineage_heading,
    lineage_ordinal,
    lineage_ordinal_label,
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
        sibling["jurisdiction"] = {"span": "folder", "meaning": "none", "status": "current", "implementation": "src.exploring"}
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
        # Tree layout: children pack INSIDE the parent, indented one step.
        self.assertGreater(shown_cli["x"], shown_house["x"])
        self.assertLessEqual(shown_cli["x"] + shown_cli["width"], shown_house["x"] + shown_house["width"])
        self.assertGreater(shown_cli["y"], shown_house["y"])
        leftover_node = next(item for item in nodes if item["id"] == "knowledge.src")
        self.assertEqual(leftover_node["x"], shown_house["x"])
        self.assertGreaterEqual(lineage_ordinal(shown_cli), 1)
        self.assertEqual("1", src_box.get("ordinal_label"))
        self.assertEqual("1-1", shown_house.get("ordinal_label"))
        self.assertEqual("1-2", leftover_node.get("ordinal_label"))
        self.assertEqual("1-1-1", shown_cli.get("ordinal_label"))
        self.assertEqual("1-1-1. cli", lineage_heading(shown_cli))
        shown_tray = next(item for item in nodes if item["id"] == "knowledge.ag2c-imgui-tray")
        self.assertEqual("1-1-2", shown_tray.get("ordinal_label"))
        labels = [
            lineage_ordinal_label(item)
            for item in nodes
            if item.get("kind") in {"module", "knowledge"} and lineage_ordinal_label(item)
        ]
        self.assertEqual(len(labels), len(set(labels)))
        self.assertEqual("cli", shown_cli["title"])
        self.assertNotIn("abstract", shown_cli)
        # Expanded container grows to wrap its subtree (the hull rect).
        self.assertGreaterEqual(shown_cli["y"] + shown_cli["height"], shown_house["y"] + 40)
        self.assertLessEqual(shown_cli["y"] + shown_cli["height"], shown_house["y"] + shown_house["height"])
        collapsed = [dict(item) for item in lineage["nodes"]]
        layout_lineage_view(collapsed, {LINEAGE_PROJECT_ID, "floor.src"})
        folded = next(item for item in collapsed if item["visual_id"] == "knowledge.ag2c@floor.src")
        self.assertEqual(lineage_card_height(folded), folded["height"])
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

    def test_lineage_nests_rooms_under_their_directory_parent_room(self) -> None:
        core = _card("knowledge.core", "knowledge", "core 松散文件", include=["src/core/**"])
        core["jurisdiction"] = {"span": "folder", "meaning": "none", "status": "current", "implementation": "cf.core-misc"}
        protocol = _card("knowledge.core-protocol", "knowledge", "协议注册表", include=["src/core/protocol/**"])
        protocol["jurisdiction"] = {"span": "file", "meaning": "named", "status": "current", "implementation": "cf.core-protocol"}
        backend = _card("knowledge.backend", "knowledge", "后端服务层", include=["src/backend/**"])
        backend["jurisdiction"] = {"span": "file", "meaning": "named", "status": "current", "implementation": "cf.backend"}
        exploring = _card("knowledge.src", "knowledge", "src exploring household", include=["src/**"])
        exploring["jurisdiction"] = {"span": "none", "meaning": "none", "status": "current", "implementation": "src.exploring"}
        lineage = build_lineage(
            {
                "project": {"name": "CartridgeFlow"},
                "cards": [
                    _card("constitution.project", "constitution", "宪章"),
                    _card("floor.src", "floor", "src", include=["src/**"]),
                    core,
                    protocol,
                    backend,
                    exploring,
                ],
                "relations": [
                    {"source": "knowledge.core", "type": "explains", "target": "floor.src"},
                    {"source": "knowledge.core-protocol", "type": "explains", "target": "floor.src"},
                    {"source": "knowledge.backend", "type": "explains", "target": "floor.src"},
                    {"source": "knowledge.src", "type": "explains", "target": "floor.src"},
                ],
                "graph": {"nodes": []},
            }
        )
        core_node = next(node for node in lineage["nodes"] if node["id"] == "knowledge.core")
        protocol_node = next(node for node in lineage["nodes"] if node["id"] == "knowledge.core-protocol")
        backend_node = next(node for node in lineage["nodes"] if node["id"] == "knowledge.backend")
        exploring_node = next(node for node in lineage["nodes"] if node["id"] == "knowledge.src")
        # A room nests under the real room whose directory strictly contains it.
        self.assertEqual("knowledge.core@floor.src", protocol_node["parent"])
        self.assertEqual(3, protocol_node["layer"])
        self.assertTrue(core_node.get("nested"))
        # Sibling top-level directories stay on the floor.
        self.assertEqual("floor.src", core_node["parent"])
        self.assertEqual("floor.src", backend_node["parent"])
        # Exploring households never swallow other rooms.
        self.assertEqual("floor.src", exploring_node["parent"])
        self.assertFalse(exploring_node.get("nested"))
        labels = {
            node["id"]: node.get("ordinal_label")
            for node in lineage["nodes"]
            if node.get("kind") == "knowledge"
        }
        self.assertTrue(labels["knowledge.core-protocol"].startswith(labels["knowledge.core"] + "-"))

    def test_lineage_groups_crowded_file_span_rooms_by_subdirectory(self) -> None:
        room = _card("knowledge.backend", "knowledge", "后端服务层", include=["src/backend/**"])
        room["jurisdiction"] = {"span": "file", "meaning": "named", "status": "current", "implementation": "cf.backend"}
        root_files = ["main.py", "api_models.py", "state.py", "store.py"]
        router_files = ["agent.py", "runs.py", "studio.py"]
        cards = [
            _card("constitution.project", "constitution", "宪章"),
            _card("floor.src", "floor", "src", include=["src/**"]),
            room,
        ]
        relations = [{"source": "knowledge.backend", "type": "explains", "target": "floor.src"}]
        for name in root_files + router_files:
            rel = f"src/backend/{name}" if name in root_files else f"src/backend/routers/{name}"
            card_id = "knowledge.backend-" + name.removesuffix(".py")
            cards.append(_card(card_id, "knowledge", name, include=[rel], references=[rel]))
            relations.append({"source": card_id, "type": "explains", "target": "floor.src"})
        lineage = build_lineage(
            {
                "project": {"name": "CartridgeFlow"},
                "cards": cards,
                "relations": relations,
                "graph": {"nodes": []},
            }
        )
        by_id = {node["id"]: node for node in lineage["nodes"]}
        group = next((node for node in lineage["nodes"] if node.get("kind") == "group"), None)
        self.assertIsNotNone(group)
        self.assertEqual("knowledge.backend@floor.src", group["parent"])
        self.assertEqual("routers/", group["title"])
        self.assertEqual("3 张文件卡", group["status"])
        self.assertEqual("src/backend/routers", group["path"])
        for name in router_files:
            card_id = "knowledge.backend-" + name.removesuffix(".py")
            self.assertEqual(group["visual_id"], by_id[card_id]["parent"])
            self.assertEqual(4, by_id[card_id]["layer"])
        for name in root_files:
            card_id = "knowledge.backend-" + name.removesuffix(".py")
            self.assertEqual("knowledge.backend@floor.src", by_id[card_id]["parent"])
        # The room status still counts every file card, grouped or not.
        self.assertEqual("7 张文件卡", by_id["knowledge.backend"]["status"])
        # Ordinals flow through the group node.
        self.assertTrue(group.get("ordinal_label"))
        child_labels = [by_id["knowledge.backend-" + n.removesuffix(".py")]["ordinal_label"] for n in router_files]
        self.assertTrue(all(label.startswith(group["ordinal_label"] + "-") for label in child_labels))
        # Groups stay collapsed by default but lay out cleanly when expanded.
        from ag2c_gui.graph import LINEAGE_PROJECT_ID, layout_lineage_view

        expanded = {node["visual_id"] for node in lineage["nodes"] if node.get("kind") == "module" and not node.get("empty")}
        expanded.add(LINEAGE_PROJECT_ID)
        self.assertNotIn(group["visual_id"], expanded)
        expanded.add(group["visual_id"])
        expanded.add("knowledge.backend@floor.src")
        view = [dict(node) for node in lineage["nodes"]]
        layout_lineage_view(view, expanded)
        visible_ids = {node.get("visual_id") for node in view if not node.get("hidden")}
        self.assertIn(group["visual_id"], visible_ids)
        for name in router_files:
            card_id = "knowledge.backend-" + name.removesuffix(".py")
            self.assertIn(by_id[card_id]["visual_id"], visible_ids)
        self.assertEqual([], lineage_step_overlaps(lineage["nodes"], expanded))

    def test_expanded_group_packs_children_inline_below_the_header(self) -> None:
        room = _card("knowledge.backend", "knowledge", "后端服务层", include=["src/backend/**"])
        room["jurisdiction"] = {"span": "file", "meaning": "named", "status": "current", "implementation": "cf.backend"}
        root_files = ["main.py", "api_models.py", "state.py", "store.py"]
        router_files = ["agent.py", "runs.py", "studio.py"]
        cards = [
            _card("constitution.project", "constitution", "宪章"),
            _card("floor.src", "floor", "src", include=["src/**"]),
            room,
        ]
        relations = [{"source": "knowledge.backend", "type": "explains", "target": "floor.src"}]
        for name in root_files + router_files:
            rel = f"src/backend/{name}" if name in root_files else f"src/backend/routers/{name}"
            card_id = "knowledge.backend-" + name.removesuffix(".py")
            cards.append(_card(card_id, "knowledge", name, include=[rel], references=[rel]))
            relations.append({"source": card_id, "type": "explains", "target": "floor.src"})
        lineage = build_lineage(
            {
                "project": {"name": "CartridgeFlow"},
                "cards": cards,
                "relations": relations,
                "graph": {"nodes": []},
            }
        )
        by_id = {node["id"]: node for node in lineage["nodes"]}
        group = next(node for node in lineage["nodes"] if node.get("kind") == "group")

        from ag2c_gui.graph import LINEAGE_PROJECT_ID, layout_lineage_view

        expanded = {node["visual_id"] for node in lineage["nodes"] if node.get("kind") == "module" and not node.get("empty")}
        expanded.add(LINEAGE_PROJECT_ID)
        expanded.add("knowledge.backend@floor.src")
        expanded.add(group["visual_id"])
        view = [dict(node) for node in lineage["nodes"]]
        layout_lineage_view(view, expanded)
        laid = {str(node.get("visual_id") or node.get("id")): node for node in view}
        placed_group = laid[group["visual_id"]]
        gx, gy = float(placed_group["x"]), float(placed_group["y"])
        # Tree layout: the group grows in place; children stack below it.
        self.assertTrue(placed_group.get("group"))
        last_bottom = gy
        for name in router_files:
            child = laid[by_id["knowledge.backend-" + name.removesuffix(".py")]["visual_id"]]
            # Same column as the group header, indented, stacked below it.
            self.assertGreater(float(child["x"]), gx)
            self.assertLess(float(child["x"]), gx + float(placed_group["width"]))
            self.assertGreaterEqual(float(child["y"]), last_bottom)
            last_bottom = float(child["y"]) + float(child["height"])
            self.assertFalse(child.get("hidden"))
        # The group hull grows to contain every inline child.
        self.assertGreaterEqual(float(placed_group["y"]) + float(placed_group["height"]), last_bottom)
        self.assertEqual([], lineage_step_overlaps(lineage["nodes"], expanded))

    def test_lineage_marks_rehome_sources_and_drop_targets(self) -> None:
        room = _card("knowledge.backend", "knowledge", "后端服务层", include=["src/backend/**"])
        room["jurisdiction"] = {"span": "file", "meaning": "named", "status": "current", "implementation": "cf.backend"}
        exploring = _card("knowledge.src", "knowledge", "src exploring household", include=["src/**"])
        exploring["jurisdiction"] = {"span": "none", "meaning": "none", "status": "current", "implementation": "src.exploring"}
        cards = [
            _card("constitution.project", "constitution", "宪章"),
            _card("floor.src", "floor", "src", include=["src/**"]),
            room,
            exploring,
        ]
        relations = [
            {"source": "knowledge.backend", "type": "explains", "target": "floor.src"},
            {"source": "knowledge.src", "type": "explains", "target": "floor.src"},
        ]
        files = ["main.py", "state.py", "store.py", "a.py", "b.py", "c.py"]
        for name in files:
            rel = f"src/backend/routers/{name}"
            card_id = "knowledge.backend-" + name.removesuffix(".py")
            cards.append(_card(card_id, "knowledge", name, include=[rel], references=[rel]))
            relations.append({"source": card_id, "type": "explains", "target": "floor.src"})
        lineage = build_lineage(
            {
                "project": {"name": "CartridgeFlow"},
                "cards": cards,
                "relations": relations,
                "graph": {"nodes": []},
            }
        )
        by_id = {node["id"]: node for node in lineage["nodes"]}
        # Real rooms accept drops; exploring households never do.
        self.assertEqual("knowledge.backend", by_id["knowledge.backend"].get("rehomeRoom"))
        self.assertEqual("", by_id["knowledge.backend"].get("rehomeSubdir"))
        self.assertNotIn("rehomeRoom", by_id["knowledge.src"])
        # Single-file Python cards are drag sources.
        self.assertEqual("knowledge.backend-main", by_id["knowledge.backend-main"].get("rehomeSource"))
        # Group nodes drop into their real subdirectory.
        group = next(node for node in lineage["nodes"] if node.get("kind") == "group")
        self.assertEqual("knowledge.backend", group.get("rehomeRoom"))
        self.assertEqual("routers", group.get("rehomeSubdir"))

    def test_lineage_skips_grouping_for_small_rooms(self) -> None:
        room = _card("knowledge.backend", "knowledge", "后端服务层", include=["src/backend/**"])
        room["jurisdiction"] = {"span": "file", "meaning": "named", "status": "current", "implementation": "cf.backend"}
        cards = [
            _card("constitution.project", "constitution", "宪章"),
            _card("floor.src", "floor", "src", include=["src/**"]),
            room,
        ]
        relations = [{"source": "knowledge.backend", "type": "explains", "target": "floor.src"}]
        for name in ("main.py", "state.py"):
            rel = f"src/backend/routers/{name}"
            card_id = "knowledge.backend-" + name.removesuffix(".py")
            cards.append(_card(card_id, "knowledge", name, include=[rel], references=[rel]))
            relations.append({"source": card_id, "type": "explains", "target": "floor.src"})
        lineage = build_lineage(
            {
                "project": {"name": "Demo"},
                "cards": cards,
                "relations": relations,
                "graph": {"nodes": []},
            }
        )
        self.assertEqual([], [node for node in lineage["nodes"] if node.get("kind") == "group"])

    def test_floor_title_ignores_root_file_include_patterns(self) -> None:
        lineage = build_lineage(
            {
                "project": {"name": "CartridgeFlow"},
                "cards": [
                    _card("constitution.project", "constitution", "宪章"),
                    _card(
                        "floor.root",
                        "floor",
                        "Project root files",
                        include=[".gitattributes", "README.md", "VERSION"],
                    ),
                    _card("floor.src", "floor", "src area", include=["src/**"]),
                    _card("floor.docs", "floor", "docs area", include=["docs/guide.md"]),
                ],
                "relations": [],
                "graph": {"nodes": []},
            }
        )
        titles = {node["id"]: node["title"] for node in lineage["nodes"] if node.get("kind") == "module"}
        self.assertEqual("Project root files", titles["floor.root"])
        self.assertEqual("src", titles["floor.src"])
        self.assertEqual("docs", titles["floor.docs"])

    def test_lineage_ordinals_use_hyphenated_layer_paths(self) -> None:
        lineage = build_lineage(
            {
                "project": {"name": "Demo"},
                "cards": [
                    _card("constitution.project", "constitution", "宪章"),
                    _card("floor.a", "floor", "a", include=["a/**"]),
                    _card("floor.b", "floor", "b", include=["b/**"]),
                    _card("knowledge.a1", "knowledge", "第一", include=["a/one.py"]),
                    _card("knowledge.a2", "knowledge", "第二", include=["a/two.py"]),
                    _card("knowledge.b1", "knowledge", "另一块", include=["b/one.py"]),
                ],
                "relations": [
                    {"source": "knowledge.a1", "type": "explains", "target": "floor.a"},
                    {"source": "knowledge.a2", "type": "explains", "target": "floor.a"},
                    {"source": "knowledge.b1", "type": "explains", "target": "floor.b"},
                ],
                "graph": {"nodes": []},
            }
        )
        by_id = {node["id"]: node for node in lineage["nodes"]}
        self.assertEqual("1", by_id["floor.a"]["ordinal_label"])
        self.assertEqual("2", by_id["floor.b"]["ordinal_label"])
        self.assertEqual("1-1", by_id["knowledge.a1"]["ordinal_label"])
        self.assertEqual("1-2", by_id["knowledge.a2"]["ordinal_label"])
        self.assertEqual("2-1", by_id["knowledge.b1"]["ordinal_label"])
        self.assertEqual("2-1. 另一块", lineage_heading(by_id["knowledge.b1"]))

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
            # Tree layout: the expanded project wraps its floors; sibling
            # floors still never overlap each other.
            self.assertGreaterEqual(left["x"], project["x"])
            self.assertGreaterEqual(left["y"], project["y"])
            self.assertLessEqual(left["y"] + left["height"], project["y"] + project["height"])
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
        # Tree layout: floors stack below the project root, indented one step.
        self.assertAlmostEqual(float(project["x"]) + LINEAGE_TREE_INDENT, min(module_xs), delta=0.5)
        stack_top = min(float(node["y"]) for node in modules)
        stack_bot = max(float(node["y"]) + float(node["height"]) for node in modules)
        self.assertGreater(stack_top, float(project["y"]))
        self.assertLessEqual(stack_bot, float(project["y"]) + float(project["height"]))

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

    def test_lineage_hides_empty_leftover_parent_when_asked(self) -> None:
        leftover = {
            "id": "knowledge.src",
            "type": "knowledge",
            "title": "src leftover parent",
            "summary": "只挡住空的父目录",
            "scopes": [{"target": "app", "include": ["src/**"], "exclude": ["src/ag2c/**"], "ownership": "primary"}],
            "checkers": [],
            "references": [],
            "jurisdiction": {"implementation": "src.exploring", "meaning": "none", "status": "current"},
        }
        cards = [
            _card("constitution.project", "constitution", "宪章"),
            _card("floor.src", "floor", "src", include=["src/**"]),
            leftover,
            _card("knowledge.ag2c", "knowledge", "src/ag2c package", include=["src/ag2c/**"]),
        ]
        relations = [
            {"source": "knowledge.src", "type": "explains", "target": "floor.src"},
            {"source": "knowledge.ag2c", "type": "explains", "target": "floor.src"},
        ]
        details = {"project": {"name": "Demo"}, "cards": cards, "relations": relations, "graph": {"nodes": []}}
        counts = {"knowledge.src": 0, "knowledge.ag2c": 30}

        shown = build_lineage(details, file_counts=counts)
        self.assertIn("knowledge.src", {node.get("id") for node in shown["nodes"]})

        hidden = build_lineage(details, hide_empty_leftovers=True, file_counts=counts)
        ids = {node.get("id") for node in hidden["nodes"]}
        self.assertNotIn("knowledge.src", ids)
        self.assertIn("knowledge.ag2c", ids)
        # Ordinals stay gapless: the remaining card takes 1-1, not 1-2.
        child = next(node for node in hidden["nodes"] if node.get("id") == "knowledge.ag2c")
        self.assertEqual("1-1", child.get("ordinal_label"))

    def test_lineage_keeps_placeholder_with_files_or_without_excludes(self) -> None:
        leftover = {
            "id": "knowledge.src",
            "type": "knowledge",
            "title": "src leftover parent",
            "summary": "",
            "scopes": [{"target": "app", "include": ["src/**"], "exclude": ["src/ag2c/**"], "ownership": "primary"}],
            "checkers": [],
            "references": [],
            "jurisdiction": {"implementation": "src.exploring", "meaning": "none", "status": "current"},
        }
        fresh = {
            "id": "knowledge.new",
            "type": "knowledge",
            "title": "new exploring household",
            "summary": "",
            "scopes": [{"target": "app", "include": ["src/new/**"], "exclude": [], "ownership": "primary"}],
            "checkers": [],
            "references": [],
            "jurisdiction": {"implementation": "new.exploring", "meaning": "none", "status": "current"},
        }
        cards = [
            _card("constitution.project", "constitution", "宪章"),
            _card("floor.src", "floor", "src", include=["src/**"]),
            leftover,
            fresh,
        ]
        relations = [
            {"source": "knowledge.src", "type": "explains", "target": "floor.src"},
            {"source": "knowledge.new", "type": "explains", "target": "floor.src"},
        ]
        details = {"project": {"name": "Demo"}, "cards": cards, "relations": relations, "graph": {"nodes": []}}
        # A leftover parent that still owns files stays visible.
        with_files = build_lineage(details, hide_empty_leftovers=True, file_counts={"knowledge.src": 2, "knowledge.new": 0})
        self.assertIn("knowledge.src", {node.get("id") for node in with_files["nodes"]})
        # A fresh exploring room without carved-out excludes is not a leftover parent:
        # even with zero files it stays visible, while the empty leftover parent hides.
        no_files = build_lineage(details, hide_empty_leftovers=True, file_counts={"knowledge.src": 0, "knowledge.new": 0})
        ids = {node.get("id") for node in no_files["nodes"]}
        self.assertNotIn("knowledge.src", ids)
        self.assertIn("knowledge.new", ids)

    def test_lineage_hides_legacy_leftover_parent_too(self) -> None:
        legacy = {
            "id": "knowledge.packaging",
            "type": "knowledge",
            "title": "packaging leftover parent",
            "summary": "只保住排除",
            "scopes": [{"target": "app", "include": ["packaging/**"], "exclude": ["packaging/windows/**"], "ownership": "primary"}],
            "checkers": [],
            "references": [],
            "jurisdiction": {"implementation": "packaging.exploring", "meaning": "none", "status": "legacy"},
        }
        cards = [
            _card("constitution.project", "constitution", "宪章"),
            _card("floor.packaging", "floor", "packaging", include=["packaging/**"]),
            legacy,
            _card("knowledge.packaging-windows", "knowledge", "Windows tray packager", include=["packaging/windows/**"]),
        ]
        relations = [
            {"source": "knowledge.packaging", "type": "explains", "target": "floor.packaging"},
            {"source": "knowledge.packaging-windows", "type": "explains", "target": "floor.packaging"},
        ]
        details = {"project": {"name": "Demo"}, "cards": cards, "relations": relations, "graph": {"nodes": []}}
        hidden = build_lineage(details, hide_empty_leftovers=True, file_counts={"knowledge.packaging": 0, "knowledge.packaging-windows": 3})
        ids = {node.get("id") for node in hidden["nodes"]}
        self.assertNotIn("knowledge.packaging", ids)
        self.assertIn("knowledge.packaging-windows", ids)

    def test_two_expanded_sibling_combos_do_not_overlap(self) -> None:
        def household(card_id, title, prefix):
            card = _card(card_id, "knowledge", title, include=[f"{prefix}/**"])
            card["jurisdiction"] = {"span": "file", "meaning": "named", "status": "current", "capability": card_id, "implementation": f"{card_id}.main"}
            return card

        cards = [
            _card("constitution.project", "constitution", "宪章"),
            _card("floor.src", "floor", "src", include=["src/**"]),
            household("knowledge.aaa", "aaa package", "src/aaa"),
            household("knowledge.bbb", "bbb package", "src/bbb"),
        ]
        relations = [
            {"source": "knowledge.aaa", "type": "explains", "target": "floor.src"},
            {"source": "knowledge.bbb", "type": "explains", "target": "floor.src"},
        ]
        for index in range(4):
            card_id = f"knowledge.aaa-f{index}"
            cards.append(_card(card_id, "knowledge", f"aaa f{index}", include=[f"src/aaa/f{index}.py"], references=[f"src/aaa/f{index}.py"]))
            relations.append({"source": card_id, "type": "explains", "target": "floor.src"})
        for index in range(2):
            card_id = f"knowledge.bbb-f{index}"
            cards.append(_card(card_id, "knowledge", f"bbb f{index}", include=[f"src/bbb/f{index}.py"], references=[f"src/bbb/f{index}.py"]))
            relations.append({"source": card_id, "type": "explains", "target": "floor.src"})
        lineage = build_lineage({"project": {"name": "Demo"}, "cards": cards, "relations": relations, "graph": {"nodes": []}})
        expanded = {LINEAGE_PROJECT_ID, "floor.src", "knowledge.aaa@floor.src", "knowledge.bbb@floor.src"}
        nodes = [dict(item) for item in lineage["nodes"]]
        self.assertEqual([], lineage_step_overlaps(nodes, expanded))
        # Tree layout: the second sibling room starts below the first
        # sibling's whole subtree (its grown hull).
        aaa = next(node for node in nodes if node.get("id") == "knowledge.aaa")
        bbb = next(node for node in nodes if node.get("id") == "knowledge.bbb")
        self.assertGreaterEqual(float(bbb["y"]), float(aaa["y"]) + float(aaa["height"]))

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
        tree_w = LINEAGE_TREE_ROOT_W - LINEAGE_TREE_INDENT
        self.assertEqual(tree_w, src["width"])
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
        self.assertAlmostEqual(float(kids[0]["y"]), src["y"] + LINEAGE_COLLAPSED_H + LINEAGE_CARD_GAP_Y, delta=0.5)
        front = next(item for item in nodes if item["visual_id"] == "floor.front")
        self.assertEqual(LINEAGE_COLLAPSED_H, front["height"])
        self.assertEqual(tree_w, front["width"])
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
        # Tree layout: an expanded container wraps its children exactly —
        # one indent step wider than the uniform child width.
        self.assertAlmostEqual(float(proto["width"]), LINEAGE_TREE_INDENT + width, delta=0.5)
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
