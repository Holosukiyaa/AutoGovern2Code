from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import bootstrap

from ag2c.checks import run_checks
from ag2c.config import discover_manifest, load_manifest, load_policy
from ag2c.enrollment import enroll_project
from ag2c.acceptance import assess_product
from ag2c.errors import AG2CError, ConfigurationError, WidenError
from ag2c.gitops import git
from ag2c.govern import apply_change, pending_updates, retrieve_guidance, settle_pending
from ag2c.household_commands import (
    confirm_retirement,
    read_census,
    register_household,
    renew_exploring,
    retire_household,
    review_census,
    set_household_enforcement,
    tighten_household,
)
from ag2c.tasks import start_task
from ag2c.graph import build_governance_graph
from ag2c.households import census_path, enforce_households
from ag2c.index import build_index
from ag2c.slicer import compile_slice
from ag2c.util import digest_file
from support import git_project


class HouseholdTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.root = git_project(Path(self.workspace.name) / "project")
        enroll_project(self.root, project_id="household-test", skill_root=Path(self.workspace.name) / "skills")
        self.manifest = load_manifest(discover_manifest(self.root))

    def register(self, card_id="knowledge.current", **overrides):
        values = {"card_id": card_id, "title": "Main implementation", "summary": "Executes the current value module.", "includes": ["src/**"], "excludes": [], "floors": ["floor.src"], "capability": "value", "implementation": "value.current", "status": "current", "entrypoints": ["src/value.py"], "command": [sys.executable, "-m", "unittest", "discover", "-s", "tests"], "actor": "reviewer", "reason": "Reviewed the real implementation and its tests"}
        values.update(overrides)
        return register_household(self.root, **values)

    def survey(self, *card_ids):
        return review_census(self.root, card_ids=list(card_ids), all_cards=not card_ids, actor="reviewer", reason="Inspected directory ownership and implementation bindings")

    def household(self, card_id="knowledge.current"):
        return next(item for item in read_census(self.root)["households"] if item["id"] == card_id)

    def enforce(self, card_id="knowledge.current", path="src/value.py", checkers=None):
        policy = load_policy(self.manifest)
        entry = {"entries": {"paths": [{"target": "app", "path": path}]}, "cards": [{"id": card_id}]}
        enforce_households(self.manifest, policy, entry, set(checkers or ["check." + card_id]))

    def test_floor_and_readme_do_not_claim_source_directories(self):
        before = read_census(self.root)
        self.assertEqual(0, before["counts"]["jurisdictions"])
        self.assertGreater(before["counts"]["unowned"], 0)
        self.assertTrue(any(item["path"] == "src/value.py" for item in before["gaps"]))
        self.register()
        after = read_census(self.root)
        self.assertFalse(any(item["path"] == "src/value.py" for item in after["gaps"]))
        self.assertTrue(any(item["path"] == "tests/test_value.py" for item in after["gaps"]))

    def test_census_tracks_time_commit_summary_and_content_not_refresh(self):
        self.register()
        self.assertEqual("never", self.household()["freshness"])
        self.survey()
        record = self.household()["last_census"]
        self.assertEqual(git(self.root, "rev-parse", "HEAD").strip(), record["project_revisions"]["app"]["commit"])
        self.assertEqual("reviewer", record["actor"])
        self.assertTrue(record["surveyed_at"])
        self.assertEqual("initial", record["last_source_change"][0]["summary"])
        self.assertEqual("current", self.household()["freshness"])
        (self.root / "src/value.py").write_text("VALUE = 2\n", encoding="utf-8")
        self.assertEqual("stale", self.household()["freshness"])
        self.assertEqual(record, self.household()["last_census"])
        self.survey("knowledge.current")
        current = self.household()
        self.assertEqual("current", current["freshness"])
        self.assertEqual(2, len(current["history"]))
        self.assertTrue(current["last_census"]["project_revisions"]["app"]["dirty_paths"])
        self.assertEqual(record["id"], current["last_census"]["previous"])

    def test_add_remove_and_scope_declaration_change_invalidate_census(self):
        self.register()
        self.survey()
        extra = self.root / "src/extra.py"
        extra.write_text("VALUE = 3\n", encoding="utf-8")
        self.assertEqual("stale", self.household()["freshness"])
        self.survey()
        extra.unlink()
        self.assertEqual("stale", self.household()["freshness"])
        self.survey()
        self.register(summary="Now describes a different responsibility")
        self.assertEqual("stale", self.household()["freshness"])

    def test_unrelated_commit_does_not_make_unchanged_scope_stale(self):
        self.register()
        self.survey()
        (self.root / "VERSION").write_text("2.0.0\n", encoding="utf-8")
        git(self.root, "add", "VERSION")
        git(self.root, "-c", "core.hooksPath=", "commit", "-m", "release metadata")
        self.assertEqual("current", self.household()["freshness"])
        self.assertEqual("2.0.0", read_census(self.root)["revisions"]["app"]["version"])
        self.assertNotEqual(read_census(self.root)["revisions"]["app"]["commit"], self.household()["last_census"]["project_revisions"]["app"]["commit"])

    def test_exclusions_and_ignored_files_are_not_silently_claimed(self):
        (self.root / "src/old").mkdir()
        (self.root / "src/old/app.js").write_text("export default 1\n", encoding="utf-8")
        self.register(excludes=["src/old/**"])
        self.assertTrue(any(item["path"] == "src/old/app.js" for item in read_census(self.root)["gaps"]))
        self.survey()
        (self.root / "src/__pycache__").mkdir()
        (self.root / "src/__pycache__/temp.pyc").write_bytes(b"cache")
        self.assertEqual("current", self.household()["freshness"])

    def test_document_and_invalid_registration_do_not_mutate_policy(self):
        before = digest_file(self.manifest.policy_path)
        with self.assertRaises(ConfigurationError):
            self.register(includes=["src/value.py"])
        self.assertEqual(before, digest_file(self.manifest.policy_path))
        with self.assertRaises(ConfigurationError):
            self.register(card_id="Invalid Id")
        self.assertEqual(before, digest_file(self.manifest.policy_path))

    def test_replacement_cannot_hide_wrong_implementation_checks(self):
        (self.root / "src/old").mkdir()
        (self.root / "src/old/app.js").write_text("export default 1\n", encoding="utf-8")
        self.register(excludes=["src/old/**"])
        self.register("knowledge.old", includes=["src/old/**"], entrypoints=["src/old/app.js"], implementation="value.old", status="legacy", replaced_by="knowledge.current", command=None, checkers=["check.knowledge.current"])
        self.survey()
        set_household_enforcement(self.root, enabled=True, actor="reviewer", reason="Require implementation-specific checks")
        self.assertIn("implementation-check-mismatch", {issue["code"] for issue in self.household("knowledge.old")["issues"]})
        with self.assertRaisesRegex(AG2CError, "implementation-check-mismatch"):
            self.enforce("knowledge.old", "src/old/app.js", ["check.knowledge.current"])

    def test_actual_diff_paths_require_census_and_cannot_drop_bound_check(self):
        self.register()
        set_household_enforcement(self.root, enabled=True, actor="reviewer", reason="Enforce reviewed ownership")
        with self.assertRaisesRegex(AG2CError, "census-never"):
            self.enforce()
        self.survey()
        self.enforce()
        with self.assertRaisesRegex(AG2CError, "implementation-check-not-selected"):
            self.enforce(checkers=["check.diff"])
        with self.assertRaisesRegex(AG2CError, "changed-code-without-unique-household"):
            self.enforce(path="new-unowned/deleted.py")

    def test_competing_frontends_and_partial_directory_coverage_stay_visible(self):
        for name in ("one", "two", "three"):
            directory = self.root / "src" / name
            directory.mkdir()
            (directory / "main.tsx").write_text("export default 1\n", encoding="utf-8")
            self.register("knowledge." + name, includes=["src/" + name + "/**"], entrypoints=[], capability="frontend", implementation="frontend." + name, command=None)
        report = read_census(self.root)
        self.assertEqual(3, len(report["implementations"][0]["current"]))
        self.assertTrue(report["implementations"][0]["competing"])
        graph = build_governance_graph({"census": report})
        self.assertTrue(any(combo["id"] == "directory:app:src" and "unowned" in combo["flags"] for combo in graph["combos"]))
        self.assertTrue(any(node["id"] == "capability:frontend" and "multiple" in node["flags"] for node in graph["nodes"]))

    def test_retirement_with_remaining_code_and_overlap_are_not_green(self):
        self.register()
        self.register("knowledge.old", implementation="value.old", entrypoints=[], status="retired", replaced_by="knowledge.current", command=None)
        report = read_census(self.root)
        self.assertGreater(report["counts"]["ambiguous"], 0)
        self.assertIn("retired-code-remains", {item["code"] for item in self.household("knowledge.old")["issues"]})

    def test_settle_does_not_renew_census_and_generic_card_api_cannot_erase_it(self):
        self.register()
        self.survey()
        (self.root / "src/value.py").write_text("VALUE = 3\n", encoding="utf-8")
        settle_pending(self.root, actor="reviewer", reason="Refresh ordinary document discovery")
        self.assertEqual("stale", self.household()["freshness"])
        with self.assertRaisesRegex(AG2CError, "govern household"):
            apply_change(self.root, action="remove", kind="card", card_id="knowledge.current", actor="reviewer", reason="Try generic deletion")

    def test_tampered_census_is_not_shown_as_current(self):
        self.register()
        self.survey()
        path = census_path(self.manifest)
        state = json.loads(path.read_text(encoding="utf-8"))
        state["records"][0]["summary"] = "tampered"
        path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(AG2CError, "digest"):
            read_census(self.root)

    def test_slicer_keeps_old_checks_and_adds_replacement_regression(self):
        (self.root / "src/old").mkdir()
        (self.root / "src/old/app.js").write_text("export default 1\n", encoding="utf-8")
        self.register(excludes=["src/old/**"])
        self.register("knowledge.old", includes=["src/old/**"], entrypoints=[], implementation="value.old", status="legacy", replaced_by="knowledge.current")
        policy = load_policy(self.manifest)
        build_index(self.manifest, policy)
        route = compile_slice(self.manifest, policy, path_specs=["app:src/old/app.js"])
        checks = {item["id"] for item in route["check_plan"]}
        self.assertTrue({"check.knowledge.old", "check.knowledge.current"}.issubset(checks))

    def test_relabelling_the_same_test_is_not_implementation_evidence(self):
        self.register()
        self.register("knowledge.other", implementation="other", capability="other")
        self.assertIn("implementation-check-reused", {issue["code"] for issue in self.household()["issues"]})

    def test_required_implementation_skip_is_failure(self):
        self.register(command=[sys.executable, "-c", "print('AG2C_SKIP: unavailable'); raise SystemExit(78)"])
        self.survey()
        set_household_enforcement(self.root, enabled=True, actor="reviewer", reason="Skipping the implementation is not passing")
        policy = load_policy(self.manifest)
        build_index(self.manifest, policy)
        route = compile_slice(self.manifest, policy, path_specs=["app:src/value.py"])
        report = run_checks(self.manifest, policy, route)
        result = next(item for item in report["results"] if item["id"] == "check.knowledge.current")
        self.assertEqual("failed", result["status"])
        self.assertIn("Required implementation check was skipped", result["stderr"])

    def test_recomputed_tamper_digest_still_requires_ledger_evidence(self):
        from ag2c.util import digest_json

        self.register()
        self.survey()
        path = census_path(self.manifest)
        state = json.loads(path.read_text(encoding="utf-8"))
        record = state["records"][0]
        record["reason"] = "forged"
        record["digest"] = digest_json({key: value for key, value in record.items() if key != "digest"})
        path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(AG2CError, "ledger"):
            read_census(self.root)

    def test_missing_census_cache_cannot_hide_reviewed_ledger_records(self):
        self.register()
        self.survey()
        census_path(self.manifest).unlink()
        with self.assertRaisesRegex(AG2CError, "missing"):
            read_census(self.root)

    def test_floor_link_must_cover_the_actual_source(self):
        self.register(floors=["floor.tests"])
        self.assertIn("floor-scope-mismatch", {issue["code"] for issue in self.household()["issues"]})

    def test_legacy_requires_replacement_and_cycles_are_rejected_atomically(self):
        self.register(status="legacy")
        self.assertIn("replacement-missing", {issue["code"] for issue in self.household()["issues"]})
        self.register("knowledge.other", status="legacy", replaced_by="knowledge.current", implementation="other", command=None)
        before = digest_file(self.manifest.policy_path)
        with self.assertRaisesRegex(ConfigurationError, "cycle"):
            self.register(status="legacy", replaced_by="knowledge.other")
        self.assertEqual(before, digest_file(self.manifest.policy_path))

    def _add_code(self, relative: str, body: str = "VALUE = 1\n") -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    def test_exploring_src_glob_with_subdirectories_is_not_opaque(self):
        self._add_code("src/core/runner.py")
        self._add_code("src/frontend/main.tsx", "export default 1\n")
        self.register(meaning="none", grain="subtree")
        record = self.household()
        self.assertEqual("exploring", record["identity"])
        self.assertNotIn("opaque-claimed", {issue["code"] for issue in record["issues"]})
        self.assertIn("app:src/core", record["child_directories"])
        self.assertIn("app:src/frontend", record["child_directories"])
        self.survey("knowledge.current")
        self.assertEqual("exploring", self.household()["identity"])
        graph = build_governance_graph({"census": read_census(self.root)})
        node = next(item for item in graph["nodes"] if item["id"] == "knowledge.current")
        self.assertIn("exploring", node["flags"])
        self.assertNotIn("opaque", node["flags"])
        self.assertFalse(node["lazy"])

    def test_named_src_glob_without_children_is_opaque_and_cannot_be_recorded(self):
        self._add_code("src/core/runner.py")
        self._add_code("src/frontend/main.tsx", "export default 1\n")
        self.register(meaning="named", grain="directory")
        record = self.household()
        self.assertEqual("opaque", record["identity"])
        self.assertIn("opaque-claimed", {issue["code"] for issue in record["issues"]})
        self.assertIn("child-unclaimed", {issue["code"] for issue in record["issues"]})
        with self.assertRaisesRegex(AG2CError, "census-record-blocked"):
            self.survey("knowledge.current")
        graph = build_governance_graph({"census": read_census(self.root)})
        node = next(item for item in graph["nodes"] if item["id"] == "knowledge.current")
        self.assertIn("opaque", node["flags"])
        self.assertTrue(node["lazy"])

    def test_same_glob_does_not_count_as_named_children(self):
        self._add_code("src/core/runner.py")
        self.register(meaning="named")
        self.register("knowledge.shadow", meaning="named", implementation="value.shadow", entrypoints=["src/value.py"])
        record = self.household()
        self.assertEqual("opaque", record["identity"])
        self.assertIn("child-not-proper-subset", {issue["code"] for issue in record["issues"]})

    def test_proper_subset_children_clear_named_identity(self):
        self._add_code("src/core/runner.py")
        self._add_code("src/frontend/main.tsx", "export default 1\n")
        self.register(meaning="named", grain="directory", excludes=["src/core/**", "src/frontend/**"], entrypoints=["src/value.py"])
        self.register(
            "knowledge.core",
            includes=["src/core/**"],
            excludes=[],
            meaning="none",
            grain="subtree",
            implementation="value.core",
            entrypoints=["src/core/runner.py"],
            command=None,
        )
        self.register(
            "knowledge.frontend",
            includes=["src/frontend/**"],
            excludes=[],
            meaning="none",
            grain="subtree",
            capability="frontend",
            implementation="value.frontend",
            entrypoints=["src/frontend/main.tsx"],
            command=None,
        )
        record = self.household()
        self.assertEqual("named", record["identity"])
        self.assertNotIn("opaque-claimed", {issue["code"] for issue in record["issues"]})
        self.survey("knowledge.current")

    def test_tighten_cannot_loosen_and_requires_a_stricter_dimension(self):
        self.register()
        with self.assertRaisesRegex(AG2CError, "stricter"):
            tighten_household(self.root, card_id="knowledge.current", grain="subtree", actor="reviewer", reason="same grain")
        tighten_household(self.root, card_id="knowledge.current", grain="directory", actor="reviewer", reason="one notch")
        with self.assertRaises(WidenError):
            tighten_household(self.root, card_id="knowledge.current", grain="subtree", actor="reviewer", reason="try to go back")
        tighten_household(self.root, card_id="knowledge.current", meaning="named", actor="reviewer", reason="leaf can be named")
        with self.assertRaises(WidenError):
            tighten_household(self.root, card_id="knowledge.current", meaning="none", actor="reviewer", reason="cannot reopen")

    def test_tighten_to_named_without_children_is_blocked(self):
        self._add_code("src/core/runner.py")
        self.register()
        with self.assertRaisesRegex(AG2CError, "tighten-blocked"):
            tighten_household(self.root, card_id="knowledge.current", meaning="named", actor="reviewer", reason="claim named too early")
        self.assertEqual("exploring", self.household()["identity"])

    def test_tighten_grain_on_exploring_household_stays_exploring(self):
        self._add_code("src/core/runner.py")
        self.register()
        result = tighten_household(self.root, card_id="knowledge.current", grain="directory", actor="reviewer", reason="one notch tighter, still exploring")
        self.assertEqual("exploring", result["identity"])
        self.assertEqual("directory", self.household()["jurisdiction"]["grain"])
        self.assertEqual("none", self.household()["jurisdiction"]["meaning"])

    def test_renew_exploring_does_not_claim_named_or_product(self):
        self._add_code("src/core/runner.py")
        self._add_code("src/frontend/main.tsx", "export default 1\n")
        self.register(command=None)
        pending = pending_updates(self.root)
        kinds = {item["kind"] for item in pending["items"]}
        self.assertIn("tighten-or-renew", kinds)
        self.assertIn("undeclared-product", kinds)
        renewed = renew_exploring(self.root, card_id="knowledge.current", actor="reviewer", reason="still exploring the frontend tree")
        self.assertEqual("exploring", renewed["identity"])
        kinds_after = {item["kind"] for item in pending_updates(self.root)["items"]}
        self.assertNotIn("tighten-or-renew", kinds_after)
        self.assertIn("undeclared-product", kinds_after)
        self.assertEqual("exploring", self.household()["identity"])
        product = assess_product(load_policy(self.manifest))
        self.assertEqual("undeclared", product["status"])
        settled = settle_pending(self.root, actor="reviewer", reason="ordinary document settle")
        remaining = {item["kind"] for item in settled["pending"]}
        self.assertIn("undeclared-product", remaining)
        self.assertEqual("exploring", self.household()["identity"])

    def test_opaque_pending_survives_settle(self):
        self._add_code("src/core/runner.py")
        self.register(meaning="named")
        kinds = {item["kind"] for item in pending_updates(self.root)["items"]}
        self.assertIn("opaque-household", kinds)
        settled = settle_pending(self.root, actor="reviewer", reason="cannot settle a black box")
        self.assertIn("opaque-household", {item["kind"] for item in settled["pending"]})

    def test_retrieve_guidance_includes_household_identity(self):
        self.register()
        payload = retrieve_guidance(self.root, path_specs=["app:src/value.py"])
        current = next(item for item in payload["households"] if item["id"] == "knowledge.current")
        self.assertEqual("exploring", current["identity"])
        self.assertFalse(current["explained"])
        self.assertEqual("subtree", current["grain"])

    def test_narrow_start_refuses_opaque_household_debt(self):
        from support import _git

        self._add_code("src/core/runner.py")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "--no-verify", "-m", "tree")
        self.register(meaning="named")
        pending_updates(self.root)
        with self.assertRaisesRegex(AG2CError, "household-debt"):
            start_task(
                self.root,
                goal="change the managed value",
                path_specs=["app:src/value.py"],
                contract_specs=[],
                worktree_root=Path(self.workspace.name) / "worktrees",
            )

    def test_retire_marks_exploring_household_leftover(self):
        self.register()
        retire_household(self.root, card_id="knowledge.current", actor="reviewer", reason="abandon the spike")
        record = self.household()
        self.assertEqual("retired", record["jurisdiction"]["status"])
        self.assertEqual("leftover", record["identity"])


if __name__ == "__main__":
    unittest.main()
