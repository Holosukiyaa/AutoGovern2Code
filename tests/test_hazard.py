"""危房名单（hazard_report）与看板集成的单元测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import bootstrap

from ag2c.hazard import HAZARD_SCHEMA, SUGGESTIONS, hazard_report
from ag2c.ledger import append_event
from ag2c_gui.dashboard import dashboard_model

from support import bare_manifest


def _mutation_canary(manifest, *, result: str, mutation: str) -> None:
    append_event(manifest.ledger_path, "canary", {"mode": "mutation", "canary": result, "mutation": mutation})


def _write_warning_history(manifest, entries: list[dict]) -> None:
    manifest.state_dir.mkdir(parents=True, exist_ok=True)
    store = {f"fp{i}": entry for i, entry in enumerate(entries)}
    (manifest.state_dir / "warning-history.json").write_text(
        json.dumps({"schema": "ag2c.warning-history.v1", "warnings": store}, ensure_ascii=False),
        encoding="utf-8",
    )


class ClassificationTests(unittest.TestCase):
    def test_mutation_survivor_becomes_hollow_hazard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = bare_manifest(Path(directory))
            _mutation_canary(manifest, result="failed", mutation="比较符 >→>=（src/ag2c_gui/graph.py:248）")
            report = hazard_report(manifest)
            self.assertEqual(HAZARD_SCHEMA, report["schema"])
            self.assertEqual(1, len(report["hazards"]))
            hazard = report["hazards"][0]
            self.assertEqual("hollow", hazard["kind"])
            self.assertEqual("src/ag2c_gui/graph.py", hazard["target"])
            self.assertEqual(248, hazard["line"])
            self.assertEqual(SUGGESTIONS["hollow"], hazard["suggestion"])
            self.assertFalse(hazard["resolved"])
            self.assertEqual({"hollow": 1}, report["counts"])

    def test_later_passed_canary_on_same_file_marks_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = bare_manifest(Path(directory))
            _mutation_canary(manifest, result="failed", mutation="布尔 True→False（src/ag2c/receipts.py:83）")
            _mutation_canary(manifest, result="passed", mutation="布尔 True→False（src/ag2c/receipts.py:83）")
            report = hazard_report(manifest)
            self.assertEqual(1, len(report["hazards"]))
            self.assertTrue(report["hazards"][0]["resolved"])
            self.assertIn("疑似已修复", report["hazards"][0]["detail"])

    def test_warning_history_classifies_duplicate_and_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = bare_manifest(Path(directory))
            _write_warning_history(
                manifest,
                [
                    {"kind": "possible-duplicate", "key": "src/ag2c/cli.py:_json", "count": 4, "detail": "d1"},
                    {"kind": "over-budget", "key": "src/ag2c/tasks.py", "count": 2, "detail": "d2"},
                    {"kind": "cross-slice-dependency", "key": "src/ag2c/checks.py", "count": 9, "detail": "d3"},
                ],
            )
            report = hazard_report(manifest)
            by_kind = {h["kind"]: h for h in report["hazards"]}
            self.assertEqual({"duplicate", "budget"}, set(by_kind))
            self.assertEqual("src/ag2c/cli.py", by_kind["duplicate"]["target"])
            self.assertEqual("src/ag2c/tasks.py", by_kind["budget"]["target"])
            self.assertEqual(SUGGESTIONS["duplicate"], by_kind["duplicate"]["suggestion"])
            self.assertEqual(SUGGESTIONS["budget"], by_kind["budget"]["suggestion"])

    def test_stale_census_room_and_expired_card(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = bare_manifest(Path(directory))
            census = {"households": [{"id": "knowledge.ag2c", "freshness": "stale"}, {"id": "floor.src", "freshness": "current"}]}
            knowledge = [
                {"id": "knowledge.old", "status": "stale", "reasons": ["reference-digest-changed"]},
                {"id": "knowledge.ag2c", "status": "stale", "jurisdiction": True},
            ]
            with mock.patch("ag2c.households.census_report", return_value=census), mock.patch(
                "ag2c.knowledge.knowledge_status", return_value=knowledge
            ):
                report = hazard_report(manifest, policy=object())
            stale = [h for h in report["hazards"] if h["kind"] == "stale"]
            self.assertEqual({"knowledge.ag2c", "knowledge.old"}, {h["target"] for h in stale})
            self.assertTrue(all(h["suggestion"] == SUGGESTIONS["stale"] for h in stale))

    def test_no_policy_skips_stale_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = bare_manifest(Path(directory))
            report = hazard_report(manifest, policy=None)
            self.assertEqual([], report["hazards"])


class SeverityOrderingTests(unittest.TestCase):
    def test_hollow_outranks_duplicate_outranks_budget_outranks_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = bare_manifest(Path(directory))
            _mutation_canary(manifest, result="failed", mutation="比较符 >→>=（src/a.py:1）")
            _write_warning_history(
                manifest,
                [
                    {"kind": "possible-duplicate", "key": "src/b.py:_f", "count": 3, "detail": "d"},
                    {"kind": "over-budget", "key": "src/c.py", "count": 1, "detail": "d"},
                ],
            )
            census = {"households": [{"id": "knowledge.x", "freshness": "stale"}]}
            with mock.patch("ag2c.households.census_report", return_value=census), mock.patch(
                "ag2c.knowledge.knowledge_status", return_value=[]
            ):
                report = hazard_report(manifest, policy=object())
            kinds = [h["kind"] for h in report["hazards"]]
            self.assertEqual(["hollow", "duplicate", "budget", "stale"], kinds)
            severities = [h["severity"] for h in report["hazards"]]
            self.assertEqual(sorted(severities, reverse=True), severities)


class DegradationTests(unittest.TestCase):
    def test_empty_project_yields_empty_report_without_raising(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = bare_manifest(Path(directory))
            report = hazard_report(manifest)
            self.assertEqual(HAZARD_SCHEMA, report["schema"])
            self.assertEqual([], report["hazards"])
            self.assertEqual({}, report["counts"])

    def test_corrupt_ledger_and_history_still_return_a_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = bare_manifest(Path(directory))
            manifest.ledger_path.write_text("not json at all\n", encoding="utf-8")
            manifest.state_dir.mkdir(parents=True)
            (manifest.state_dir / "warning-history.json").write_text("{broken", encoding="utf-8")
            report = hazard_report(manifest)
            self.assertEqual(HAZARD_SCHEMA, report["schema"])
            self.assertEqual([], report["hazards"])


class DashboardIntegrationTests(unittest.TestCase):
    def _details(self, hazards: list[dict]) -> dict:
        return {"project": {"name": "demo"}, "hazards": {"schema": HAZARD_SCHEMA, "hazards": hazards, "counts": {}}}

    def test_hazard_section_lists_top_five_with_city_language(self) -> None:
        hazards = [
            {"target": f"src/m{i}.py", "kind": "duplicate", "severity": 30, "suggestion": "合并同类"} for i in range(6)
        ]
        model = dashboard_model(self._details(hazards), {})
        self.assertEqual(5, len(model["hazards"]))
        self.assertIn("双胞胎楼", model["hazards"][0]["text"])
        self.assertIn("合并同类", model["hazards"][0]["text"])

    def test_unresolved_hollow_raises_warn_anomaly(self) -> None:
        hazards = [{"target": "src/ag2c_gui/graph.py", "kind": "hollow", "severity": 40, "suggestion": "补杀变异测试", "resolved": False}]
        model = dashboard_model(self._details(hazards), {})
        self.assertTrue(any("危楼·无安全网" in a["text"] and a["severity"] == "warn" for a in model["anomalies"]))
        self.assertEqual("error", model["hazards"][0]["severity"])

    def test_resolved_hollow_stays_off_the_anomaly_list(self) -> None:
        hazards = [{"target": "src/ag2c/receipts.py", "kind": "hollow", "severity": 40, "suggestion": "补杀变异测试", "resolved": True}]
        model = dashboard_model(self._details(hazards), {})
        self.assertFalse(any("危楼" in a["text"] for a in model["anomalies"]))
        self.assertIn("疑似已修复", model["hazards"][0]["text"])

    def test_missing_hazards_section_degrades_silently(self) -> None:
        model = dashboard_model({"project": {"name": "demo"}}, {})
        self.assertEqual([], model["hazards"])
        self.assertEqual([], model["anomalies"])


if __name__ == "__main__":
    unittest.main()
