from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import bootstrap

from ag2c.config import discover_manifest, load_manifest, load_policy
from ag2c.enrollment import enroll_project
from ag2c.errors import AG2CError
from ag2c.gitops import git
from ag2c.govern import apply_change, ingest_project, pending_updates, retrieve_guidance, settle_pending
from ag2c.knowledge import knowledge_status, sync_knowledge

from support import git_project


class GovernanceIngestTests(unittest.TestCase):
    def test_enrollment_ingests_docs_and_detected_interfaces(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "project")
            (root / "README.md").write_text("# Demo service\nHello\n", encoding="utf-8")
            (root / "docs").mkdir()
            (root / "docs" / "guide.md").write_text("# Guide\nHow it works\n", encoding="utf-8")
            (root / "src" / "api").mkdir()
            (root / "src" / "api" / "routes.py").write_text("ROUTES = []\n", encoding="utf-8")
            git(root, "add", "--all")
            git(root, "commit", "-m", "docs and api")

            enroll_project(root, project_id="ingest-demo", skill_root=workspace / "skills")
            manifest = load_manifest(discover_manifest(root))
            policy = load_policy(manifest)
            ids = {card.card_id for card in policy.cards}
            self.assertIn("knowledge.readme-md", ids)
            self.assertIn("knowledge.docs-guide-md", ids)
            self.assertIn("boundary.src-api", ids)
            self.assertTrue(any(relation.relation_type == "explains" for relation in policy.relations))
            statuses = {item["id"]: item for item in knowledge_status(manifest, policy)}
            self.assertEqual("current", statuses["knowledge.readme-md"]["status"])

    def test_apply_requires_reason_and_records_pending_after_new_docs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "project")
            enroll_project(root, project_id="apply-demo", skill_root=workspace / "skills")
            (root / "handbook.md").write_text("# Handbook\nRules\n", encoding="utf-8")
            git(root, "add", "handbook.md")
            git(root, "-c", "core.hooksPath=", "commit", "-m", "docs: handbook")

            pending = pending_updates(root, ["handbook.md"])
            kinds = {item["kind"] for item in pending["items"]}
            self.assertIn("changed-document", kinds)

            with self.assertRaisesRegex(AG2CError, "reason"):
                apply_change(
                    root,
                    action="add",
                    kind="card",
                    card_id="knowledge.handbook-md",
                    reason="   ",
                    actor="codex",
                    include=["handbook.md"],
                )

            result = apply_change(
                root,
                action="add",
                kind="card",
                card_id="knowledge.handbook-md",
                reason="Handbook is the operator contract",
                actor="codex",
                title="Handbook",
                summary="Operator contract",
                include=["handbook.md"],
            )
            self.assertEqual("add", result["action"])
            policy = load_policy(load_manifest(discover_manifest(root)))
            self.assertEqual("knowledge", policy.card("knowledge.handbook-md").card_type)
            remaining = pending_updates(root)
            self.assertFalse(
                any(item["kind"] == "changed-document" and item["path"] == "handbook.md" for item in remaining["items"])
            )

    def test_retrieve_returns_relevant_knowledge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "project")
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            git(root, "add", "README.md")
            git(root, "commit", "-m", "readme")
            enroll_project(root, project_id="retrieve-demo", skill_root=workspace / "skills")

            guidance = retrieve_guidance(root, path_specs=["app:src/value.py"], goal="change value")
            card_ids = {card["id"] for card in guidance["cards"]}
            self.assertIn("floor.src", card_ids)
            self.assertIn("route", guidance)
            self.assertIn("households", guidance)
            src = next(item for item in guidance["households"] if item["id"] == "knowledge.src")
            self.assertEqual("exploring", src["identity"])
            self.assertFalse(src["explained"])

    def test_ingest_detects_directories_whose_files_have_spaces(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "project")
            post = root / "post"
            post.mkdir()
            (post / "la la land.html").write_text("<html></html>\n", encoding="utf-8")
            git(root, "add", "post")
            git(root, "commit", "-m", "post with spaces")
            enroll_project(root, project_id="quoted-paths", skill_root=workspace / "skills")
            policy = json.loads(load_manifest(discover_manifest(root)).policy_path.read_text(encoding="utf-8"))
            self.assertIn("post", policy["coverage"]["areas"])
            self.assertIn("floor.post", {card["id"] for card in policy["cards"]})
            self.assertNotIn("\"post", policy["coverage"]["areas"])

    def test_settle_registers_new_areas_and_clears_pending(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "project")
            enroll_project(root, project_id="settle-demo", skill_root=workspace / "skills")
            (root / "docs").mkdir()
            (root / "docs" / "guide.md").write_text("# Guide\nHow it works\n", encoding="utf-8")
            git(root, "add", "docs/guide.md")
            git(root, "-c", "core.hooksPath=", "commit", "-m", "docs: guide")

            pending = pending_updates(root)
            kinds = {item["kind"] for item in pending["items"]}
            self.assertTrue({"unowned-area", "new-document"} & kinds)
            self.assertTrue(all(item.get("title") for item in pending["items"]))

            result = settle_pending(root, actor="codex", reason="docs area was added after merge")
            self.assertIn("ingest", result["actions"])
            remaining = {item["kind"] for item in result["pending"]}
            self.assertIn("undeclared-product", remaining)
            self.assertNotIn("unowned-area", remaining)
            self.assertNotIn("new-document", remaining)
            policy = json.loads(load_manifest(discover_manifest(root)).policy_path.read_text(encoding="utf-8"))
            self.assertIn("floor.docs", {card["id"] for card in policy["cards"]})
            self.assertIn("knowledge.docs-guide-md", {card["id"] for card in policy["cards"]})
            self.assertIn("knowledge.docs", {card["id"] for card in policy["cards"]})

    def test_ingest_refreshes_new_documents_on_baseline_projects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "project")
            enroll_project(root, project_id="refresh-demo", skill_root=workspace / "skills")
            (root / "README.md").write_text("# Later readme\n", encoding="utf-8")
            git(root, "add", "README.md")
            git(root, "-c", "core.hooksPath=", "commit", "-m", "docs: readme")

            result = ingest_project(root, actor="codex", reason="README was added after enrollment")
            self.assertIn("knowledge.readme-md", result["knowledge"])
            policy = json.loads(load_manifest(discover_manifest(root)).policy_path.read_text(encoding="utf-8"))
            self.assertIn("knowledge.readme-md", {card["id"] for card in policy["cards"]})

    def test_settle_syncs_stale_knowledge_but_leaves_assertion_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = git_project(workspace / "project")
            (root / "README.md").write_text("# Demo service\nHello\n", encoding="utf-8")
            git(root, "add", "README.md")
            git(root, "commit", "-m", "readme")
            enroll_project(root, project_id="assertion-demo", skill_root=workspace / "skills")
            manifest = load_manifest(discover_manifest(root))
            policy = load_policy(manifest)

            (root / "README.md").write_text("# Demo service\nHello again\n", encoding="utf-8")
            pending = pending_updates(root)
            self.assertIn("stale-knowledge", {item["kind"] for item in pending["items"]})
            settled = settle_pending(root, actor="codex", reason="README body changed after review")
            self.assertIn("sync", settled["actions"])
            self.assertFalse(any(item["kind"] == "stale-knowledge" for item in settled["pending"]))

            (root / "README.md").write_text("# Runtime contract rewritten\nHello again\n", encoding="utf-8")
            pending = pending_updates(root)
            self.assertIn("assertion-conflict", {item["kind"] for item in pending["items"]})
            leftover = settle_pending(root, actor="codex", reason="title rewrite still needs review")
            self.assertNotIn("sync", leftover["actions"])
            self.assertTrue(any(item["kind"] == "assertion-conflict" for item in leftover["pending"]))
            statuses = {item["id"]: item for item in knowledge_status(manifest, policy)}
            self.assertEqual("conflict", statuses["knowledge.readme-md"]["status"])

            sync_knowledge(
                manifest,
                policy,
                card_ids=["knowledge.readme-md"],
                actor="codex",
                reason="Accepted the rewritten README lead",
            )
            remaining = pending_updates(root)
            self.assertFalse(any(item["kind"] == "assertion-conflict" for item in remaining["items"]))
