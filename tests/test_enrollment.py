from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bootstrap
from support import git_project

from ag2c.config import discover_manifest, load_manifest, load_policy
from ag2c.enrollment import activation_status, enroll_project, runtime_equivalent
from ag2c.errors import AG2CError
from ag2c.gitops import git, status_entries
from ag2c.govern import apply_change
from ag2c.household_commands import register_household, set_household_span, tighten_household
from ag2c.households import census_report, design_summary_for_file


class EnrollmentTests(unittest.TestCase):
    def test_enroll_allows_a_dirty_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = git_project(Path(directory) / "demo")
            (root / "src" / "value.py").write_text("VALUE = 2\n", encoding="utf-8")
            (root / "notes.txt").write_text("scratch\n", encoding="utf-8")
            skills = Path(directory) / "skills"
            dirty = status_entries(root)
            self.assertIn("src/value.py", dirty)
            self.assertIn("notes.txt", dirty)

            result = enroll_project(root, skill_root=skills, harnesses=("agents",))

            self.assertEqual("demo", result["project_id"])
            self.assertFalse(result["working_tree_changed"])
            self.assertTrue((Path(result["store"]) / "manifest.json").is_file())
            self.assertTrue(status_entries(root))
            self.assertTrue(str(git(root, "config", "--get", "ag2c.manifest")).strip())

    def test_activate_wraps_every_previous_git_hook(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = git_project(base / "demo")
            husky = root / ".husky"
            husky.mkdir()
            (husky / "pre-commit").write_text("#!/bin/sh\necho old-pre-commit\n", encoding="utf-8")
            (husky / "pre-push").write_text("#!/bin/sh\necho old-pre-push\n", encoding="utf-8")
            (husky / "commit-msg").write_text("#!/bin/sh\necho old-commit-msg\n", encoding="utf-8")
            (husky / "not-a-hook").write_text("ignore\n", encoding="utf-8")
            git(root, "config", "core.hooksPath", ".husky")
            data = base / "ag2c-data"
            skills = base / "skills"
            with patch.dict(os.environ, {"AG2C_DATA_ROOT": str(data)}, clear=False):
                result = enroll_project(root, skill_root=skills, harnesses=("agents",))
            hooks = Path(result["store"]) / "state" / "hooks"
            pre = (hooks / "pre-commit").read_text(encoding="utf-8")
            push = (hooks / "pre-push").read_text(encoding="utf-8")
            message = (hooks / "commit-msg").read_text(encoding="utf-8")
            self.assertIn("guard pre-commit", pre)
            self.assertIn((husky / "pre-commit").resolve().as_posix(), pre.replace("\\", "/"))
            self.assertIn((husky / "pre-push").resolve().as_posix(), push.replace("\\", "/"))
            self.assertNotIn("guard pre-commit", push)
            self.assertIn((husky / "commit-msg").resolve().as_posix(), message.replace("\\", "/"))
            self.assertFalse((hooks / "not-a-hook").exists())
            self.assertEqual(str(hooks.resolve()), str(git(root, "config", "--get", "core.hooksPath")).strip())
            self.assertEqual(".husky", json.loads((Path(result["store"]) / "state" / "activation.json").read_text(encoding="utf-8"))["previous_hooks_path"])

    def test_activate_forwards_default_git_hooks_and_ignores_samples(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = git_project(base / "demo")
            native = root / ".git" / "hooks"
            native.mkdir(parents=True, exist_ok=True)
            (native / "pre-push").write_text("#!/bin/sh\necho native-pre-push\n", encoding="utf-8")
            (native / "pre-commit.sample").write_text("#!/bin/sh\necho sample\n", encoding="utf-8")
            data = base / "ag2c-data"
            with patch.dict(os.environ, {"AG2C_DATA_ROOT": str(data)}, clear=False):
                result = enroll_project(root, skill_root=base / "skills", harnesses=("agents",))
            hooks = Path(result["store"]) / "state" / "hooks"
            push = (hooks / "pre-push").read_text(encoding="utf-8")
            self.assertIn((native / "pre-push").resolve().as_posix(), push.replace("\\", "/"))
            self.assertNotIn("native-pre-push", push)
            self.assertFalse((hooks / "pre-commit.sample").exists())
            self.assertIn("guard pre-commit", (hooks / "pre-commit").read_text(encoding="utf-8"))

    def test_stale_skill_home_does_not_unmanage_when_git_guard_is_on(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = git_project(base / "demo")
            skills = base / "skills"
            data = base / "ag2c-data"
            with patch.dict(os.environ, {"AG2C_DATA_ROOT": str(data)}, clear=False):
                enroll_project(root, skill_root=skills, harnesses=("agents",))
                skill_md = skills / "ag2c-governed-development" / "SKILL.md"
                skill_md.write_text("---\nname: ag2c-governed-development\nversion: 0.0.1\n---\nstale\n", encoding="utf-8")
                status = activation_status(root)
            self.assertTrue(status["managed"])
            self.assertFalse(any("Skill" in item for item in status["issues"]))

    def test_naming_src_without_child_households_is_refused_not_stored_as_opaque(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = git_project(base / "demo")
            (root / "src" / "frontend").mkdir()
            (root / "src" / "frontend" / "app.ts").write_text("export {}\n", encoding="utf-8")
            (root / "src" / "backend").mkdir()
            (root / "src" / "backend" / "api.py").write_text("VALUE = 1\n", encoding="utf-8")
            data = base / "ag2c-data"
            with patch.dict(os.environ, {"AG2C_DATA_ROOT": str(data)}, clear=False):
                enroll_project(root, skill_root=base / "skills", harnesses=("agents",))
                with self.assertRaises(AG2CError) as raised:
                    register_household(
                        root,
                        card_id="knowledge.src",
                        title="src",
                        summary="the whole tree",
                        includes=["src/**"],
                        excludes=[],
                        floors=["floor.src"],
                        capability="src",
                        implementation="src.main",
                        status="current",
                        meaning="named",
                        actor="codex",
                        reason="claim every file under src",
                    )
                self.assertIn("cannot-name-undecomposed-household", str(raised.exception))
                with self.assertRaises(AG2CError) as tightened:
                    tighten_household(
                        root,
                        card_id="knowledge.src",
                        meaning="named",
                        actor="codex",
                        reason="name the enrollment placeholder",
                    )
                self.assertIn("tighten-blocked", str(tightened.exception))
                manifest = load_manifest(discover_manifest(root), project_root=root)
                src = next(item for item in census_report(manifest, load_policy(manifest))["households"] if item["id"] == "knowledge.src")
                self.assertEqual("exploring", src["identity"])
                frontend = register_household(
                    root,
                    card_id="knowledge.frontend",
                    title="frontend",
                    summary="shipped UI",
                    includes=["src/frontend/**"],
                    excludes=[],
                    floors=["floor.src"],
                    capability="frontend",
                    implementation="frontend.main",
                    status="current",
                    meaning="named",
                    span="folder",
                    actor="codex",
                    reason="traced the UI subtree",
                )
            self.assertEqual("named", frontend["jurisdiction"]["meaning"])

    def test_parent_glob_cannot_recapture_child_household(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = git_project(base / "demo")
            (root / "src" / "frontend").mkdir()
            (root / "src" / "frontend" / "app.ts").write_text("export {}\n", encoding="utf-8")
            data = base / "ag2c-data"
            with patch.dict(os.environ, {"AG2C_DATA_ROOT": str(data)}, clear=False):
                enroll_project(root, skill_root=base / "skills", harnesses=("agents",))
                register_household(
                    root,
                    card_id="knowledge.frontend",
                    title="frontend",
                    summary="shipped UI",
                    includes=["src/frontend/**"],
                    excludes=[],
                    floors=["floor.src"],
                    capability="frontend",
                    implementation="frontend.main",
                    status="current",
                    meaning="named",
                    span="folder",
                    actor="codex",
                    reason="traced the UI subtree",
                )
                with self.assertRaises(AG2CError) as raised:
                    register_household(
                        root,
                        card_id="knowledge.src",
                        title="src",
                        summary="the whole tree",
                        includes=["src/**"],
                        excludes=[],
                        floors=["floor.src"],
                        capability="src",
                        implementation="src.main",
                        status="current",
                        meaning="named",
                        span="folder",
                        actor="codex",
                        reason="reclaim src after carving frontend",
                    )
                self.assertIn("cannot-overlap-household", str(raised.exception))
                self.assertNotIn("cannot-name-undecomposed-household", str(raised.exception))
                manifest = load_manifest(discover_manifest(root), project_root=root)
                report = census_report(manifest, load_policy(manifest))
            src = next(item for item in report["households"] if item["id"] == "knowledge.src")
            frontend = next(item for item in report["households"] if item["id"] == "knowledge.frontend")
            frontend_dir = next(item for item in report["directories"] if item["path"] == "src/frontend")
            src_excludes = [
                pattern
                for scope in src["scopes"]
                for pattern in (scope.get("exclude") or scope.get("excludes") or [])
            ]
            self.assertEqual("exploring", src["identity"])
            self.assertEqual("named", frontend["identity"])
            self.assertEqual(["knowledge.frontend"], frontend_dir["owners"])
            self.assertIn("src/frontend/**", src_excludes)
            self.assertEqual(0, report["counts"]["ambiguous"])

    def test_household_update_preserves_entrypoints_and_checkers_when_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = git_project(base / "demo")
            (root / "src" / "frontend").mkdir()
            (root / "src" / "frontend" / "app.ts").write_text("export {}\n", encoding="utf-8")
            data = base / "ag2c-data"
            with patch.dict(os.environ, {"AG2C_DATA_ROOT": str(data)}, clear=False):
                enroll_project(root, skill_root=base / "skills", harnesses=("agents",))
                register_household(
                    root,
                    card_id="knowledge.frontend",
                    title="frontend",
                    summary="shipped UI",
                    includes=["src/frontend/**"],
                    excludes=[],
                    floors=["floor.src"],
                    capability="frontend",
                    implementation="frontend.main",
                    status="current",
                    meaning="named",
                    span="folder",
                    entrypoints=["src/frontend/app.ts"],
                    checkers=["check.python"],
                    actor="codex",
                    reason="traced the UI subtree",
                )
                updated = register_household(
                    root,
                    card_id="knowledge.frontend",
                    title="frontend",
                    summary="shipped UI, revised",
                    includes=["src/frontend/**"],
                    excludes=[],
                    floors=["floor.src"],
                    capability="frontend",
                    implementation="frontend.main",
                    status="current",
                    actor="codex",
                    reason="revise the summary only",
                )
                replaced = register_household(
                    root,
                    card_id="knowledge.frontend",
                    title="frontend",
                    summary="shipped UI, rerouted",
                    includes=["src/frontend/**"],
                    excludes=[],
                    floors=["floor.src"],
                    capability="frontend",
                    implementation="frontend.main",
                    status="current",
                    entrypoints=["src/frontend/main.ts"],
                    checkers=[],
                    actor="codex",
                    reason="explicitly replace entrypoints and clear checkers",
                )
            self.assertEqual(["src/frontend/app.ts"], updated["jurisdiction"]["entrypoints"])
            self.assertEqual(["check.python"], updated["checkers"])
            self.assertEqual(["src/frontend/main.ts"], replaced["jurisdiction"]["entrypoints"])
            self.assertEqual([], replaced["checkers"])

    def test_unlabeled_household_does_not_supply_file_design(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = git_project(base / "demo")
            data = base / "ag2c-data"
            with patch.dict(os.environ, {"AG2C_DATA_ROOT": str(data)}, clear=False):
                enroll_project(root, skill_root=base / "skills", harnesses=("agents",))
                manifest = load_manifest(discover_manifest(root), project_root=root)
                policy = load_policy(manifest)
                src = next(item for item in census_report(manifest, policy)["households"] if item["id"] == "knowledge.src")
                self.assertEqual("none", (src.get("jurisdiction") or {}).get("span"))
                self.assertEqual("", design_summary_for_file(policy, src, "src/value.py"))
                tagged = set_household_span(
                    root,
                    card_id="knowledge.src",
                    span="整夹一张",
                    actor="codex",
                    reason="docs-like folder tag for the src room",
                )
                self.assertEqual("folder", tagged["span"])
                self.assertEqual("整夹一张", tagged["span_label"])
                policy = load_policy(manifest)
                src = next(item for item in census_report(manifest, policy)["households"] if item["id"] == "knowledge.src")
                self.assertEqual(src["summary"], design_summary_for_file(policy, src, "src/value.py"))

    def test_named_requires_a_coverage_tag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = git_project(base / "demo")
            data = base / "ag2c-data"
            with patch.dict(os.environ, {"AG2C_DATA_ROOT": str(data)}, clear=False):
                enroll_project(root, skill_root=base / "skills", harnesses=("agents",))
                with self.assertRaises(AG2CError) as raised:
                    tighten_household(
                        root,
                        card_id="knowledge.src",
                        meaning="named",
                        actor="codex",
                        reason="name without choosing a coverage tag",
                    )
                self.assertIn("span-unlabeled", str(raised.exception))

    def test_file_span_named_requires_per_file_cards(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = git_project(base / "demo")
            data = base / "ag2c-data"
            with patch.dict(os.environ, {"AG2C_DATA_ROOT": str(data)}, clear=False):
                enroll_project(root, skill_root=base / "skills", harnesses=("agents",))
                set_household_span(root, card_id="knowledge.src", span="file", actor="codex", reason="core files need their own cards")
                with self.assertRaises(AG2CError) as raised:
                    tighten_household(
                        root,
                        card_id="knowledge.src",
                        meaning="named",
                        actor="codex",
                        reason="name before per-file cards exist",
                    )
                self.assertIn("span-file-gap", str(raised.exception))
                apply_change(
                    root,
                    action="add",
                    kind="card",
                    card_id="knowledge.src-value",
                    actor="codex",
                    reason="explain src/value.py",
                    card_type="knowledge",
                    title="src/value.py",
                    summary="Holds VALUE for the demo.",
                    include=["src/value.py"],
                )
                apply_change(
                    root,
                    action="add",
                    kind="card",
                    card_id="knowledge.src-init",
                    actor="codex",
                    reason="explain src/__init__.py",
                    card_type="knowledge",
                    title="src/__init__.py",
                    summary="Package init.",
                    include=["src/__init__.py"],
                )
                named = tighten_household(
                    root,
                    card_id="knowledge.src",
                    meaning="named",
                    actor="codex",
                    reason="every code file has its own card",
                )
                self.assertEqual("named", named["identity"])
                manifest = load_manifest(discover_manifest(root), project_root=root)
                policy = load_policy(manifest)
                src = next(item for item in census_report(manifest, policy)["households"] if item["id"] == "knowledge.src")
                self.assertEqual("Holds VALUE for the demo.", design_summary_for_file(policy, src, "src/value.py"))
                self.assertNotEqual(src["summary"], design_summary_for_file(policy, src, "src/value.py"))

    def test_knowledge_title_is_the_abstract_at_most_20_characters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = git_project(base / "demo")
            data = base / "ag2c-data"
            with patch.dict(os.environ, {"AG2C_DATA_ROOT": str(data)}, clear=False):
                enroll_project(root, skill_root=base / "skills", harnesses=("agents",))
                apply_change(
                    root,
                    action="add",
                    kind="card",
                    card_id="knowledge.src-value",
                    actor="codex",
                    reason="Chinese title is the 摘要",
                    card_type="knowledge",
                    title="演示常量存放处",
                    summary="Holds VALUE for the demo.",
                    include=["src/value.py"],
                )
                manifest = load_manifest(discover_manifest(root), project_root=root)
                policy = load_policy(manifest)
                card = next(item for item in policy.cards if item.card_id == "knowledge.src-value")
                self.assertEqual("演示常量存放处", card.title)
                with self.assertRaises(AG2CError) as raised:
                    apply_change(
                        root,
                        action="update",
                        kind="card",
                        card_id="knowledge.src-value",
                        actor="codex",
                        reason="title too long",
                        card_type="knowledge",
                        title="这是一个超过二十个字的知识卡摘要名字啊过长",
                        include=["src/value.py"],
                    )
                self.assertIn("20", str(raised.exception))

    def test_python_and_pythonw_count_as_the_same_runtime(self) -> None:
        py = Path(r"C:\Users\Holo\AppData\Local\Programs\Python\Python312\python.exe")
        pyw = Path(r"C:\Users\Holo\AppData\Local\Programs\Python\Python312\pythonw.exe")
        if not py.is_file() or not pyw.is_file():
            self.skipTest("python.exe/pythonw.exe pair is not installed")
        self.assertTrue(runtime_equivalent([str(py), "-m", "ag2c"], [str(pyw), "-m", "ag2c"]))
        self.assertFalse(runtime_equivalent([str(py), "-m", "ag2c"], [str(py), "-m", "other"]))
