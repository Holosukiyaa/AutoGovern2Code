from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import bootstrap
from support import git_project
from test_rehome import _rewrite_abs_paths

from ag2c.config import discover_manifest, load_manifest, load_policy
from ag2c.enrollment import activate_project, activation_status, enroll_project, runtime_equivalent
from ag2c.errors import AG2CError
from ag2c.gitops import git, status_entries
from ag2c.govern import apply_change
from ag2c.index import build_index
from ag2c.household_commands import register_household, set_household_span, tighten_household
from ag2c.households import census_report, design_summary_for_file


def _enrollment_pack() -> Path:
    pack = Path(tempfile.gettempdir()) / f"ag2c-enroll-pack-{Path(__file__).stat().st_mtime_ns}"
    ready, lock = pack / ".ready", Path(str(pack) + ".lock")
    while not ready.exists():
        try:
            lock.mkdir()
        except FileExistsError:
            time.sleep(0.05)
            continue
        try:
            if not ready.exists():
                shutil.rmtree(pack, True) if pack.exists() else None
                pack.mkdir(parents=True)
                env = patch.dict(os.environ, {"AG2C_DATA_ROOT": str(pack / "ag2c-data")}, clear=False)
                env.start()
                try:
                    enroll_project(git_project(pack / "demo"), skill_root=pack / "skills", harnesses=("agents",))
                finally:
                    env.stop()
                ready.write_text("ok", encoding="utf-8")
        finally:
            try:
                lock.rmdir()
            except OSError:
                pass
    return pack

class EnrollmentFixture:
    def __init__(self, base: Path) -> None:
        self.base = base
        pack = _enrollment_pack()
        shutil.copytree(pack, base, dirs_exist_ok=True)
        self.root = (base / "demo").resolve()
        self.data = (base / "ag2c-data").resolve()
        _rewrite_abs_paths(base, [(str((pack / "demo").resolve()), str(self.root)), (str((pack / "ag2c-data").resolve()), str(self.data))])
        self._env = patch.dict(os.environ, {"AG2C_DATA_ROOT": str(self.data)}, clear=False)
        self._env.start()
        manifests = [path for path in self.data.rglob("manifest.json") if path.is_file()]
        if len(manifests) != 1:
            raise RuntimeError(f"enrollment pack copy expected one manifest, found {manifests}")
        git(self.root, "config", "ag2c.manifest", str(manifests[0]))
        payload = json.loads(manifests[0].read_text(encoding="utf-8"))
        payload["project_root"] = str(self.root)
        if "path" in payload:
            payload["path"] = str(manifests[0])
        manifests[0].write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        activate_project(self.root, skill_root=self.base / "skills", harnesses=("agents",))
        loaded = load_manifest(discover_manifest(self.root), project_root=self.root)
        build_index(loaded, load_policy(loaded))

    def stop(self) -> None:
        self._env.stop()

@contextmanager
def enrolled_demo():
    with tempfile.TemporaryDirectory() as directory:
        fx = EnrollmentFixture(Path(directory))
        try:
            yield fx
        finally:
            fx.stop()

class FirstDrillTests(unittest.TestCase):
    def _enrolled(self, directory: str, **kwargs):
        root = git_project(Path(directory) / "demo")
        return root, enroll_project(root, skill_root=Path(directory) / "skills", harnesses=("agents",), **kwargs)

    def test_enroll_result_says_seed_planted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            step = (self._enrolled(directory)[1].get("next_step") or {})
            self.assertEqual("seed-planted", step.get("action"))
            self.assertIn("Stop", step.get("why") or "")

    def test_guard_status_hints_first_drill_until_team_exists(self) -> None:
        from ag2c.ledger import append_event
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self._enrolled(directory)
            status = activation_status(root)
            self.assertEqual(("first-drill", False), ((status.get("first_drill") or {}).get("action"), any("drill" in issue or "演习" in issue for issue in status["issues"])))
            append_event(load_manifest(discover_manifest(root), project_root=root).ledger_path, "canary", {"mode": "gate", "canary": "passed"})
            self.assertIsNone(activation_status(root).get("first_drill"))

    def test_enroll_default_skips_canary_and_flag_runs_it(self) -> None:
        from ag2c.enrollment import setup_project
        with tempfile.TemporaryDirectory() as directory, patch("ag2c.enroll_ops._run_first_drill", return_value={"ran": True, "exit_code": 0}) as drill:
            self._enrolled(directory)
            drill.assert_not_called()
            _, on = self._enrolled(str(Path(directory) / "flagged"), run_first_drill=True)
            setup_project(git_project(Path(directory) / "via-setup"), skill_root=Path(directory) / "skills-setup", harnesses=("agents",), run_first_drill=True)
            self.assertEqual((0, 2), (on["first_drill_result"]["exit_code"], drill.call_count))

    def test_enroll_first_drill_failure_keeps_enrollment(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch("ag2c.enroll_ops._run_first_drill", return_value={"ran": False, "error": "boom"}):
            _, result = self._enrolled(directory, run_first_drill=True)
            self.assertEqual(("boom", True), (result["first_drill_result"]["error"], bool(result.get("project_id"))))

class EnrollmentTests(unittest.TestCase):
    def test_enroll_plants_native_suite_from_existing_test_groups(self) -> None:
        from ag2c.seed import assess_seed

        with tempfile.TemporaryDirectory() as directory:
            root = git_project(Path(directory) / "farm")
            api = root / "scripts" / "tests" / "api"
            api.mkdir(parents=True)
            (api / "test_ok.py").write_text(
                "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            data = Path(directory) / "ag2c-data"
            with patch.dict(os.environ, {"AG2C_DATA_ROOT": str(data)}, clear=False):
                result = enroll_project(root, skill_root=Path(directory) / "skills", harnesses=("agents",))
            self.assertEqual("seed-planted", (result.get("next_step") or {}).get("action"))
            self.assertIn("check.suite-api", result.get("seed", {}).get("created") or [])
            self.assertFalse((root / "tests" / "suites.py").exists())
            policy = load_policy(load_manifest(discover_manifest(root), project_root=root))
            status = assess_seed(policy, project_root=root)
            self.assertEqual("ag2c", status["sower"])
            commands = [checker.command for checker in policy.checkers if checker.checker_id == "check.suite-api"]
            self.assertEqual(1, len(commands))
            joined = " ".join(commands[0])
            self.assertIn("unittest", joined)
            self.assertIn("discover", joined)
            self.assertIn("scripts/tests/api", joined)
            self.assertNotIn("ag2c", joined)
            pack = Path(result["store"]) / "pack"
            self.assertFalse((pack / "exams").exists())

    def test_enroll_without_test_groups_writes_pack_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = git_project(Path(directory) / "bare")
            import shutil

            shutil.rmtree(root / "tests")
            data = Path(directory) / "ag2c-data"
            with patch.dict(os.environ, {"AG2C_DATA_ROOT": str(data)}, clear=False):
                result = enroll_project(root, skill_root=Path(directory) / "skills", harnesses=("agents",))
            pack = Path(result["store"]) / "pack"
            self.assertTrue((pack / "exams" / "smoke" / "test_pack_smoke.py").is_file())
            self.assertTrue((pack / "run_exam.py").is_file())
            self.assertIn("check.suite-smoke", result.get("seed", {}).get("created") or [])
            self.assertFalse((root / "tests" / "suites.py").exists())
            policy = load_policy(load_manifest(discover_manifest(root), project_root=root))
            commands = [checker.command for checker in policy.checkers if checker.checker_id == "check.suite-smoke"]
            self.assertEqual(1, len(commands))
            joined = " ".join(commands[0])
            self.assertIn("run_exam.py", joined)
            self.assertIn("smoke", joined)

    def test_skipped_product_checks_are_not_incomplete(self) -> None:
        from ag2c.acceptance import PRODUCT_CHECKED, PRODUCT_INCOMPLETE, PRODUCT_NOT_RUN, assess_product
        from ag2c.model import Checker, Coverage, Policy

        policy = Policy(
            path=Path("policy.json"),
            cards=(),
            relations=(),
            contracts=(),
            checkers=(
                Checker(
                    checker_id="check.knowledge.ag2c-gui",
                    stage="scenario",
                    target_id="app",
                    command=("python", "-B", "scripts/check_desktop_boot.py"),
                    cwd=".",
                    timeout=600,
                    always=False,
                ),
            ),
            coverage=Coverage(level="none", strategy="", managed_by="", areas=()),
        )
        skipped = assess_product(
            policy,
            verification={
                "checker_results": [
                    {"id": "check.python", "stage": "floor", "status": "skipped"},
                    {"id": "check.knowledge.ag2c-gui", "stage": "scenario", "status": "skipped", "skip_reason": "docs-only"},
                ]
            },
        )
        self.assertEqual(PRODUCT_NOT_RUN, skipped["status"])
        self.assertNotEqual(PRODUCT_INCOMPLETE, skipped["status"])
        passed = assess_product(
            policy,
            verification={"checker_results": [{"id": "check.knowledge.ag2c-gui", "stage": "scenario", "status": "passed"}]},
        )
        self.assertEqual(PRODUCT_CHECKED, passed["status"])

    def test_census_version_mismatch_is_not_never_or_stale(self) -> None:
        from ag2c.households import _census_freshness

        self.assertEqual(
            "version-mismatch",
            _census_freshness(
                {"code_version": "0.0.1", "scope_digest": "a", "declaration_digest": "b"},
                "a",
                "b",
                "0.11.0",
            ),
        )
        self.assertEqual(
            "stale",
            _census_freshness(
                {"code_version": "0.11.0", "scope_digest": "old", "declaration_digest": "b"},
                "a",
                "b",
                "0.11.0",
            ),
        )

    def test_apply_floor_budget_lines_without_include(self) -> None:
        from ag2c.govern import apply_change

        with tempfile.TemporaryDirectory() as directory:
            root = git_project(Path(directory) / "floors")
            data = Path(directory) / "ag2c-data"
            with patch.dict(os.environ, {"AG2C_DATA_ROOT": str(data)}, clear=False):
                enroll_project(root, skill_root=Path(directory) / "skills", harnesses=("agents",))
            policy = load_policy(load_manifest(discover_manifest(root), project_root=root))
            floor_id = next(card.card_id for card in policy.cards if card.card_type == "floor")
            apply_change(
                root,
                action="update",
                kind="card",
                card_id=floor_id,
                actor="grok",
                reason="raise floor cap",
                budget_lines=4321,
            )
            again = load_policy(load_manifest(discover_manifest(root), project_root=root))
            floor = next(card for card in again.cards if card.card_id == floor_id)
            self.assertEqual(4321, int(floor.budget_lines or 0))

    def test_enroll_host_skips_sow_and_still_enrolls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = git_project(Path(directory) / "hosty")
            (root / "src" / "ag2c").mkdir(parents=True)
            (root / "src" / "ag2c" / "__init__.py").write_text("", encoding="utf-8")
            data = Path(directory) / "ag2c-data"
            with patch.dict(os.environ, {"AG2C_DATA_ROOT": str(data)}, clear=False):
                result = enroll_project(root, skill_root=Path(directory) / "skills", harnesses=("agents",))
            self.assertTrue(result.get("project_id"))
            self.assertEqual("seed-planted", (result.get("next_step") or {}).get("action"))
            self.assertEqual("skipped-host", result.get("seed", {}).get("action"))
            self.assertFalse((root / "tests" / "suites.py").exists())

    def test_enroll_allows_a_dirty_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = git_project(Path(directory) / "demo")
            (root / "src" / "value.py").write_text("VALUE = 2\n", encoding="utf-8")
            (root / "notes.txt").write_text("scratch\n", encoding="utf-8")
            skills = Path(directory) / "skills"
            dirty = status_entries(root)
            self.assertIn("src/value.py", dirty)
            self.assertIn("notes.txt", dirty)
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}, clear=False):
                result = enroll_project(root, skill_root=skills, harnesses=("agents",))
            store = Path(result["store"]); policy = json.loads((store / "policy.json").read_text(encoding="utf-8")); reg = policy["regulator"]
            self.assertEqual(("demo", False, True, True, True, True), (result["project_id"], result["working_tree_changed"], store.joinpath("manifest.json").is_file(), bool(status_entries(root)), bool(str(git(root, "config", "--get", "ag2c.manifest")).strip()), "git_identity" not in result))
            self.assertEqual(("configured", False, True, "https://api.deepseek.com/v1", "deepseek-v4-flash", "DEEPSEEK_API_KEY", True, False, False), (result["regulator"]["status"], result["regulator"]["finish_allowed"], reg["enabled"], reg["endpoint"], reg["model"], reg["api_key_env"], reg["strict"], "worker_model" in reg, "proxy" in policy))
            self.assertNotIn("do not inherit", result["regulator"]["why"])

    def test_enroll_hints_when_git_identity_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = git_project(Path(directory) / "demo")
            git(root, "config", "--local", "--unset-all", "user.name", check=False)
            git(root, "config", "--local", "--unset-all", "user.email", check=False)
            blank = Path(directory) / "blank-home"; blank.mkdir()
            env = {"HOME": str(blank), "USERPROFILE": str(blank), "GIT_CONFIG_GLOBAL": str(blank / "g"), "GIT_CONFIG_SYSTEM": str(blank / "s"), "AG2C_DATA_ROOT": str(Path(directory) / "ag2c-data")}
            with patch.dict(os.environ, env, clear=False):
                result = enroll_project(root, skill_root=Path(directory) / "skills", harnesses=("agents",))
            self.assertEqual(("demo", "set-git-identity"), (result["project_id"], result["git_identity"]["action"]))
            self.assertIn("user.name", result["git_identity"]["missing"])
            self.assertFalse(str(git(root, "config", "--local", "--get", "user.name", check=False)).strip())

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
        with enrolled_demo() as fx:
            root = fx.root
            (root / "src" / "frontend").mkdir()
            (root / "src" / "frontend" / "app.ts").write_text("export {}\n", encoding="utf-8")
            (root / "src" / "backend").mkdir()
            (root / "src" / "backend" / "api.py").write_text("VALUE = 1\n", encoding="utf-8")
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
        with enrolled_demo() as fx:
            root = fx.root
            (root / "src" / "frontend").mkdir()
            (root / "src" / "frontend" / "app.ts").write_text("export {}\n", encoding="utf-8")
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
        with enrolled_demo() as fx:
            root = fx.root
            (root / "src" / "frontend").mkdir()
            (root / "src" / "frontend" / "app.ts").write_text("export {}\n", encoding="utf-8")
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
        with enrolled_demo() as fx:
            root = fx.root
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
        with enrolled_demo() as fx:
            root = fx.root
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
        with enrolled_demo() as fx:
            root = fx.root
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
        with enrolled_demo() as fx:
            root = fx.root
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


class ProvidesConventionsTests(unittest.TestCase):
    """Card shelf (provides) and room constitution (conventions): schema, preserve-on-update, reuse menu."""

    def test_apply_preserves_provides_and_conventions_when_omitted(self) -> None:
        with enrolled_demo() as fx:
            root = fx.root
            apply_change(
                root,
                action="add",
                kind="card",
                card_id="knowledge.src-value",
                actor="codex",
                reason="explain src/value.py",
                card_type="knowledge",
                title="值常量",
                summary="Holds VALUE for the demo.",
                include=["src/value.py"],
                provides=["值常量 VALUE"],
                conventions="模块级只读常量",
            )
            apply_change(
                root,
                action="update",
                kind="card",
                card_id="knowledge.src-value",
                actor="codex",
                reason="retitle only, shelf untouched",
                title="演示值常量",
                include=["src/value.py"],
            )
            manifest = load_manifest(discover_manifest(root), project_root=root)
            card = next(item for item in load_policy(manifest).cards if item.card_id == "knowledge.src-value")
            self.assertEqual("演示值常量", card.title)
            self.assertEqual(("值常量 VALUE",), card.provides)
            self.assertEqual("模块级只读常量", card.conventions)
            apply_change(
                root,
                action="update",
                kind="card",
                card_id="knowledge.src-value",
                actor="codex",
                reason="replace the shelf",
                include=["src/value.py"],
                provides=["VALUE 新能力"],
            )
            card = next(item for item in load_policy(manifest).cards if item.card_id == "knowledge.src-value")
            self.assertEqual(("VALUE 新能力",), card.provides)
            self.assertEqual("模块级只读常量", card.conventions)

    def test_apply_rejects_invalid_provides_without_touching_policy(self) -> None:
        with enrolled_demo() as fx:
            root = fx.root
            apply_change(
                root,
                action="add",
                kind="card",
                card_id="knowledge.src-value",
                actor="codex",
                reason="explain src/value.py",
                card_type="knowledge",
                title="值常量",
                summary="Holds VALUE for the demo.",
                include=["src/value.py"],
                provides=["值常量 VALUE"],
            )
            manifest = load_manifest(discover_manifest(root), project_root=root)
            before = manifest.policy_path.read_text(encoding="utf-8")
            with self.assertRaises(AG2CError) as raised:
                apply_change(
                    root,
                    action="update",
                    kind="card",
                    card_id="knowledge.src-value",
                    actor="codex",
                    reason="bad shelf entry",
                    include=["src/value.py"],
                    provides=["ok", 42],
                )
            self.assertIn("provides", str(raised.exception))
            self.assertEqual(before, manifest.policy_path.read_text(encoding="utf-8"))

    def test_household_update_preserves_unpassed_jurisdiction_and_shelf_fields(self) -> None:
        with enrolled_demo() as fx:
            root = fx.root
            (root / "src" / "frontend").mkdir()
            (root / "src" / "frontend" / "app.py").write_text("A = 1\n", encoding="utf-8")
            register_household(
                root,
                card_id="knowledge.frontend",
                title="前端",
                summary="shipped UI",
                includes=["src/frontend/**"],
                excludes=[],
                floors=["floor.src"],
                capability="frontend",
                implementation="frontend.app",
                status="current",
                meaning="named",
                span="folder",
                provides=["UI 装配 assemble_view"],
                conventions="状态集中 AppState",
                actor="codex",
                reason="claim frontend",
            )
            updated = register_household(
                root,
                card_id="knowledge.frontend",
                title="前端",
                summary="shipped UI v2",
                includes=["src/frontend/**"],
                excludes=[],
                floors=["floor.src"],
                capability="frontend",
                implementation="frontend.app",
                status="current",
                actor="codex",
                reason="refresh summary only",
            )
            self.assertEqual("named", updated["jurisdiction"]["meaning"])
            self.assertEqual("folder", updated["jurisdiction"]["span"])
            self.assertEqual("subtree", updated["jurisdiction"]["grain"])
            manifest = load_manifest(discover_manifest(root), project_root=root)
            card = next(item for item in load_policy(manifest).cards if item.card_id == "knowledge.frontend")
            self.assertEqual(("UI 装配 assemble_view",), card.provides)
            self.assertEqual("状态集中 AppState", card.conventions)

    def test_guidance_reuse_menu_lists_working_set_provides_only(self) -> None:
        from ag2c.govern import retrieve_guidance

        with enrolled_demo() as fx:
            root = fx.root
            apply_change(
                root,
                action="add",
                kind="card",
                card_id="knowledge.src-value",
                actor="codex",
                reason="explain src/value.py",
                card_type="knowledge",
                title="值常量",
                summary="Holds VALUE for the demo.",
                include=["src/value.py"],
                provides=["值常量 VALUE"],
                conventions="模块级只读常量",
            )
            apply_change(
                root,
                action="add",
                kind="card",
                card_id="knowledge.tests-value",
                actor="codex",
                reason="explain tests/test_value.py",
                card_type="knowledge",
                title="值测试",
                summary="Tests VALUE.",
                include=["tests/test_value.py"],
                provides=["测试基座 ValueTests"],
            )
            guidance = retrieve_guidance(root, path_specs=["app:src/value.py"])
            menu = {item["id"]: item for item in guidance["reuse_menu"]}
            self.assertIn("knowledge.src-value", menu)
            self.assertEqual(["值常量 VALUE"], menu["knowledge.src-value"]["provides"])
            self.assertNotIn("knowledge.tests-value", menu)
            conventions = {item["id"]: item for item in guidance["conventions"]}
            self.assertEqual("模块级只读常量", conventions["knowledge.src-value"]["conventions"])
            self.assertNotIn("knowledge.tests-value", conventions)

    def test_guidance_reuse_menu_is_empty_when_nobody_provides(self) -> None:
        from ag2c.govern import retrieve_guidance

        with enrolled_demo() as fx:
            root = fx.root
            guidance = retrieve_guidance(root, path_specs=["app:src/value.py"])
            self.assertEqual([], guidance["reuse_menu"])
            self.assertEqual([], guidance["conventions"])
