from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bootstrap  # noqa: F401
from support import git_project

from ag2c.config import discover_manifest, load_manifest
from ag2c.enrollment import enroll_project
from ag2c.errors import AG2CError
from ag2c.gitops import git
from ag2c.govern import _read_json, apply_change
from ag2c.household_commands import register_household, review_census
from ag2c.rehome import python_module_name, rehome_file_card, rewrite_module_imports
from ag2c.tasks import task_record

ACTOR = "tester"
REASON = "rehome engine tests"


def _card_include(root: Path, card_id: str) -> list[str]:
    manifest = load_manifest(discover_manifest(root), project_root=root)
    raw = _read_json(manifest.policy_path)
    card = next(item for item in raw["cards"] if item["id"] == card_id)
    return [pattern for scope in card.get("scopes") or [] for pattern in scope.get("include") or []]


class ModuleNameTests(unittest.TestCase):
    def test_walks_up_while_init_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src" / "pkg" / "sub").mkdir(parents=True)
            (root / "src" / "__init__.py").write_text("", encoding="utf-8")
            (root / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
            (root / "src" / "pkg" / "sub" / "__init__.py").write_text("", encoding="utf-8")
            self.assertEqual("src.pkg.a", python_module_name(root, "src/pkg/a.py"))
            self.assertEqual("src.pkg.sub.a", python_module_name(root, "src/pkg/sub/a.py"))

    def test_stops_at_non_package_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src" / "pkg").mkdir(parents=True)
            (root / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
            self.assertEqual("pkg.a", python_module_name(root, "src/pkg/a.py"))


class RewriteTests(unittest.TestCase):
    def test_rewrites_imports_and_patch_strings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pkg").mkdir()
            target = root / "pkg" / "b.py"
            target.write_text(
                "from src.pkg.a import VALUE\n"
                "import src.pkg.a\n"
                "patch('src.pkg.a.VALUE')\n"
                "from src.pkg.a2 import OTHER\n"
                "import other.src.pkg.a\n",
                encoding="utf-8",
            )
            changed = rewrite_module_imports(root, "src.pkg.a", "src.pkg.sub.a")
            self.assertEqual(["pkg/b.py"], changed)
            text = target.read_text(encoding="utf-8")
            self.assertIn("from src.pkg.sub.a import VALUE", text)
            self.assertIn("import src.pkg.sub.a\n", text)
            self.assertIn("patch('src.pkg.sub.a.VALUE')", text)
            # Lookalikes stay untouched.
            self.assertIn("from src.pkg.a2 import OTHER", text)
            self.assertIn("import other.src.pkg.a\n", text)

    def test_same_module_is_a_noop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.py").write_text("import src.pkg.a\n", encoding="utf-8")
            self.assertEqual([], rewrite_module_imports(root, "src.pkg.a", "src.pkg.a"))


class RehomeFixture:
    def __init__(self, base: Path) -> None:
        self.base = base
        self.root = git_project(base / "demo")
        self.data = base / "ag2c-data"
        self._env = patch.dict(os.environ, {"AG2C_DATA_ROOT": str(self.data)}, clear=False)
        self._env.start()
        enroll_project(self.root, skill_root=base / "skills", harnesses=("agents",))
        pkg = self.root / "src" / "pkg"
        (pkg / "sub").mkdir(parents=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "sub" / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "a.py").write_text("VALUE_A = 'alpha'\n", encoding="utf-8")
        (pkg / "b.py").write_text("from src.pkg.a import VALUE_A\n\nVALUE_B = VALUE_A + '-beta'\n", encoding="utf-8")
        (pkg / "sub" / "c.py").write_text("VALUE_C = 'gamma'\n", encoding="utf-8")
        (self.root / "tests" / "test_pkg.py").write_text(
            "import unittest\nfrom src.pkg.b import VALUE_B\n\n"
            "class PkgTests(unittest.TestCase):\n"
            "    def test_chain(self):\n"
            "        self.assertEqual(VALUE_B, 'alpha-beta')\n",
            encoding="utf-8",
        )
        git(self.root, "add", "--all")
        # The enrolled guard hooks canonical commits; fixture setup bypasses it.
        git(self.root, "commit", "--no-verify", "-m", "pkg fixture")
        # Child household first: a named folder room is refused while a direct
        # child directory stays unclaimed.
        register_household(
            self.root,
            card_id="knowledge.pkg-sub",
            title="pkg/sub",
            summary="pkg sub room",
            includes=["src/pkg/sub/**"],
            excludes=[],
            floors=["floor.src"],
            capability="pkg-sub",
            implementation="pkg.sub",
            status="current",
            meaning="named",
            span="folder",
            actor=ACTOR,
            reason=REASON,
        )
        register_household(
            self.root,
            card_id="knowledge.pkg",
            title="pkg",
            summary="pkg room",
            includes=["src/pkg/**"],
            excludes=["src/pkg/sub/**"],
            floors=["floor.src"],
            capability="pkg",
            implementation="pkg.main",
            status="current",
            meaning="named",
            span="folder",
            actor=ACTOR,
            reason=REASON,
        )
        apply_change(
            self.root,
            action="add",
            kind="card",
            card_id="knowledge.pkg-a",
            card_type="knowledge",
            title="a.py",
            summary="module a",
            include=["src/pkg/a.py"],
            actor=ACTOR,
            reason=REASON,
        )
        review_census(self.root, card_ids=["knowledge.pkg", "knowledge.pkg-sub"], all_cards=False, actor=ACTOR, reason=REASON)

    def stop(self) -> None:
        self._env.stop()


class RehomePipelineTests(unittest.TestCase):
    def test_rehome_moves_file_rewrites_imports_and_merges(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = RehomeFixture(Path(directory))
            try:
                result = rehome_file_card(
                    fixture.root,
                    card_id="knowledge.pkg-a",
                    target_room="knowledge.pkg",
                    target_subdir="sub",
                    actor=ACTOR,
                    reason=REASON,
                )
                self.assertTrue(result["merged"])
                self.assertEqual("src/pkg/a.py", result["from"])
                self.assertEqual("src/pkg/sub/a.py", result["to"])
                # The file physically moved on the canonical checkout.
                self.assertFalse((fixture.root / "src" / "pkg" / "a.py").exists())
                self.assertTrue((fixture.root / "src" / "pkg" / "sub" / "a.py").is_file())
                # Imports were rewritten and carried through the merge.
                b_text = (fixture.root / "src" / "pkg" / "b.py").read_text(encoding="utf-8")
                self.assertIn("from src.pkg.sub.a import VALUE_A", b_text)
                self.assertIn("src/pkg/b.py", result["rewritten"])
                # The card scope follows the file.
                self.assertEqual(["src/pkg/sub/a.py"], _card_include(fixture.root, "knowledge.pkg-a"))
                # The governed task completed instead of bypassing the loop.
                self.assertEqual("completed", task_record(fixture.root, result["task"])["state"])
                # The moved module still imports and runs.
                import subprocess
                import sys

                run = subprocess.run(
                    [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                    cwd=fixture.root,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(0, run.returncode, run.stderr)
            finally:
                fixture.stop()

    def test_failed_verify_abandons_and_rolls_back_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = RehomeFixture(Path(directory))
            try:
                with patch("ag2c.rehome.verify_task", return_value={"passed": False}):
                    with self.assertRaises(AG2CError) as raised:
                        rehome_file_card(
                            fixture.root,
                            card_id="knowledge.pkg-a",
                            target_room="knowledge.pkg",
                            target_subdir="sub",
                            actor=ACTOR,
                            reason=REASON,
                        )
                self.assertIn("verification failed", str(raised.exception))
                # Nothing moved on canonical and the card scope rolled back.
                self.assertTrue((fixture.root / "src" / "pkg" / "a.py").is_file())
                self.assertFalse((fixture.root / "src" / "pkg" / "sub" / "a.py").exists())
                self.assertEqual(["src/pkg/a.py"], _card_include(fixture.root, "knowledge.pkg-a"))
            finally:
                fixture.stop()


class RehomeRefusalTests(unittest.TestCase):
    def _fixture(self, directory: str) -> RehomeFixture:
        return RehomeFixture(Path(directory))

    def test_refuses_non_python_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(directory)
            try:
                (fixture.root / "src" / "pkg" / "notes.md").write_text("# notes\n", encoding="utf-8")
                apply_change(
                    fixture.root,
                    action="add",
                    kind="card",
                    card_id="knowledge.pkg-notes",
                    card_type="knowledge",
                    title="notes",
                    summary="notes",
                    include=["src/pkg/notes.md"],
                    actor=ACTOR,
                    reason=REASON,
                )
                with self.assertRaises(AG2CError) as raised:
                    rehome_file_card(
                        fixture.root,
                        card_id="knowledge.pkg-notes",
                        target_room="knowledge.pkg",
                        target_subdir="sub",
                        actor=ACTOR,
                        reason=REASON,
                    )
                self.assertIn("Python files only", str(raised.exception))
            finally:
                fixture.stop()

    def test_refuses_package_markers_and_relative_imports(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(directory)
            try:
                apply_change(
                    fixture.root,
                    action="add",
                    kind="card",
                    card_id="knowledge.pkg-init",
                    card_type="knowledge",
                    title="init",
                    summary="package marker",
                    include=["src/pkg/__init__.py"],
                    actor=ACTOR,
                    reason=REASON,
                )
                with self.assertRaises(AG2CError) as raised:
                    rehome_file_card(
                        fixture.root,
                        card_id="knowledge.pkg-init",
                        target_room="knowledge.pkg",
                        target_subdir="sub",
                        actor=ACTOR,
                        reason=REASON,
                    )
                self.assertIn("package marker", str(raised.exception))

                (fixture.root / "src" / "pkg" / "rel.py").write_text(
                    "from .a import VALUE_A\n", encoding="utf-8"
                )
                apply_change(
                    fixture.root,
                    action="add",
                    kind="card",
                    card_id="knowledge.pkg-rel",
                    card_type="knowledge",
                    title="rel",
                    summary="relative imports",
                    include=["src/pkg/rel.py"],
                    actor=ACTOR,
                    reason=REASON,
                )
                with self.assertRaises(AG2CError) as raised:
                    rehome_file_card(
                        fixture.root,
                        card_id="knowledge.pkg-rel",
                        target_room="knowledge.pkg",
                        target_subdir="sub",
                        actor=ACTOR,
                        reason=REASON,
                    )
                self.assertIn("relative imports", str(raised.exception))
            finally:
                fixture.stop()

    def test_refuses_same_dir_collision_escape_and_unknown_targets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(directory)
            try:
                with self.assertRaises(AG2CError) as raised:
                    rehome_file_card(
                        fixture.root,
                        card_id="knowledge.pkg-a",
                        target_room="knowledge.pkg",
                        actor=ACTOR,
                        reason=REASON,
                    )
                self.assertIn("already lives", str(raised.exception))

                (fixture.root / "src" / "pkg" / "sub" / "a.py").write_text("CLASH = 1\n", encoding="utf-8")
                with self.assertRaises(AG2CError) as raised:
                    rehome_file_card(
                        fixture.root,
                        card_id="knowledge.pkg-a",
                        target_room="knowledge.pkg",
                        target_subdir="sub",
                        actor=ACTOR,
                        reason=REASON,
                    )
                self.assertIn("already exists", str(raised.exception))
                (fixture.root / "src" / "pkg" / "sub" / "a.py").unlink()

                with self.assertRaises(AG2CError) as raised:
                    rehome_file_card(
                        fixture.root,
                        card_id="knowledge.pkg-a",
                        target_room="knowledge.pkg",
                        target_subdir="../escape",
                        actor=ACTOR,
                        reason=REASON,
                    )
                self.assertIn("must stay inside the room", str(raised.exception))

                with self.assertRaises(AG2CError) as raised:
                    rehome_file_card(
                        fixture.root,
                        card_id="knowledge.pkg-a",
                        target_room="knowledge.nope",
                        target_subdir="sub",
                        actor=ACTOR,
                        reason=REASON,
                    )
                self.assertIn("not a real room", str(raised.exception))

                with self.assertRaises(AG2CError) as raised:
                    rehome_file_card(
                        fixture.root,
                        card_id="knowledge.nope",
                        target_room="knowledge.pkg",
                        target_subdir="sub",
                        actor=ACTOR,
                        reason=REASON,
                    )
                self.assertIn("unknown knowledge card", str(raised.exception))
            finally:
                fixture.stop()


if __name__ == "__main__":
    unittest.main()
