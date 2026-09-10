"""危房名单（hazard_report）与看板集成的单元测试。"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import bootstrap

from ag2c.errors import AG2CError
from ag2c.hazard import HAZARD_SCHEMA, SUGGESTIONS, _warning_freshness, dismiss_hazard, hazard_report, load_dismissals
from ag2c.ledger import append_event, read_events
from ag2c_gui.dashboard import dashboard_model

from support import _git, bare_manifest, write_project


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
            # 校准后：查重区只认实时扫描，bare 夹具无目标文件 → 化石记录不上榜；
            # 预算区维持历史驱动。
            self.assertEqual({"budget"}, set(by_kind))
            self.assertEqual("src/ag2c/tasks.py", by_kind["budget"]["target"])
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


def _verification(manifest, *, outcome: str, reason: str = "") -> None:
    regulator: dict = {"outcome": outcome}
    if reason:
        regulator["reason"] = reason
    append_event(manifest.ledger_path, "task-verification", {"task_id": "t", "regulator": regulator})


class RegulatorAbsentTests(unittest.TestCase):
    def test_three_consecutive_unavailable_becomes_hazard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = bare_manifest(Path(directory))
            for _ in range(3):
                _verification(manifest, outcome="unavailable", reason="regulator call failed: 401")
            report = hazard_report(manifest)
            self.assertEqual(1, len(report["hazards"]))
            hazard = report["hazards"][0]
            self.assertEqual("regulator-absent", hazard["kind"])
            self.assertEqual("regulator", hazard["target"])
            self.assertEqual(3, hazard["count"])
            self.assertIn("401", hazard["detail"])
            self.assertEqual(SUGGESTIONS["regulator-absent"], hazard["suggestion"])
            self.assertEqual({"regulator-absent": 1}, report["counts"])

    def test_below_threshold_stays_silent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = bare_manifest(Path(directory))
            for _ in range(2):
                _verification(manifest, outcome="unavailable", reason="regulator call failed: 401")
            self.assertEqual([], hazard_report(manifest)["hazards"])

    def test_passed_verification_breaks_the_streak(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = bare_manifest(Path(directory))
            for _ in range(3):
                _verification(manifest, outcome="unavailable", reason="regulator call failed: 401")
            _verification(manifest, outcome="passed")
            self.assertEqual([], hazard_report(manifest)["hazards"])

    def test_rejected_verification_also_proves_regulator_online(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = bare_manifest(Path(directory))
            for _ in range(3):
                _verification(manifest, outcome="unavailable", reason="invalid-verdict: junk")
            _verification(manifest, outcome="rejected")
            self.assertEqual([], hazard_report(manifest)["hazards"])

    def test_not_configured_is_not_absence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = bare_manifest(Path(directory))
            for _ in range(5):
                _verification(manifest, outcome="unavailable", reason="not-configured")
            self.assertEqual([], hazard_report(manifest)["hazards"])

    def test_streak_counts_only_from_the_latest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = bare_manifest(Path(directory))
            for _ in range(3):
                _verification(manifest, outcome="unavailable", reason="regulator call failed: 401")
            _verification(manifest, outcome="passed")
            for _ in range(2):
                _verification(manifest, outcome="unavailable", reason="regulator call failed: 401")
            self.assertEqual([], hazard_report(manifest)["hazards"])

    def test_detail_reports_the_latest_reason(self) -> None:
        """连续样本 reason 互不相同：detail 必须反映最新一次，而非最旧。"""
        with tempfile.TemporaryDirectory() as directory:
            manifest = bare_manifest(Path(directory))
            _verification(manifest, outcome="unavailable", reason="old-500")
            _verification(manifest, outcome="unavailable", reason="mid-502")
            _verification(manifest, outcome="unavailable", reason="new-401")
            hazard = hazard_report(manifest)["hazards"][0]
            self.assertIn("new-401", hazard["detail"])
            self.assertNotIn("old-500", hazard["detail"])

    def test_latest_reason_wins_even_without_timestamps(self) -> None:
        """occurred_at 缺失时也不许被更旧样本覆盖（直接喂纯函数）。"""
        from ag2c.hazard import _regulator_absent_hazards

        events = [
            {"event_type": "task-verification", "occurred_at": "",
             "payload": {"regulator": {"outcome": "unavailable", "reason": "old-500"}}},
            {"event_type": "task-verification", "occurred_at": "",
             "payload": {"regulator": {"outcome": "unavailable", "reason": "mid-502"}}},
            {"event_type": "task-verification", "occurred_at": "",
             "payload": {"regulator": {"outcome": "unavailable", "reason": "new-401"}}},
        ]
        hazards = _regulator_absent_hazards(events)
        self.assertEqual(1, len(hazards))
        self.assertIn("new-401", hazards[0]["detail"])
        self.assertNotIn("old-500", hazards[0]["detail"])


class SeverityOrderingTests(unittest.TestCase):
    def test_hollow_outranks_duplicate_outranks_budget_outranks_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = bare_manifest(Path(directory))
            _mutation_canary(manifest, result="failed", mutation="比较符 >→>=（src/a.py:1）")
            live_pair = {
                "file": "src/b.py", "name": "_f", "lines": 9,
                "other_file": "src/a.py", "other_name": "_g", "other_lines": 9, "match": "相似",
            }
            _write_warning_history(
                manifest,
                [
                    {"kind": "possible-duplicate", "key": "src/b.py:_f", "count": 3, "detail": "d"},
                    {"kind": "over-budget", "key": "src/c.py", "count": 1, "detail": "d"},
                ],
            )
            census = {"households": [{"id": "knowledge.x", "freshness": "stale"}]}
            # 查重区现在是实时扫描：mock 掉扫描器，专注验证排序与计数接续
            with mock.patch("ag2c.checks.scan_duplicate_pairs", return_value=[live_pair]), mock.patch(
                "ag2c.households.census_report", return_value=census
            ), mock.patch(
                "ag2c.knowledge.knowledge_status", return_value=[]
            ):
                report = hazard_report(manifest, policy=object())
            kinds = [h["kind"] for h in report["hazards"]]
            self.assertEqual(["hollow", "duplicate", "budget", "stale"], kinds)
            severities = [h["severity"] for h in report["hazards"]]
            self.assertEqual(sorted(severities, reverse=True), severities)
            # 历史计数接续到实时扫描结果上（排序依据）
            duplicate = report["hazards"][1]
            self.assertEqual(3, duplicate["count"])
            self.assertEqual("live-scan", duplicate["evidence"]["store"])


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


class FreshnessTests(unittest.TestCase):
    """保鲜：警告历史只记"上次触发"，文件在 last_seen 之后改过的记录降级 unconfirmed。

    校准后查重区走实时扫描（命中即 standing），保鲜机制只服务预算区。"""

    def _repo(self, root: Path) -> None:
        _git(root, "init", "-b", "main")
        _git(root, "config", "user.name", "T")
        _git(root, "config", "user.email", "t@example.invalid")

    def _commit_file(self, root: Path, relpath: str, content: str, when: str) -> None:
        path = root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        env = dict(os.environ, GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
        subprocess.run(["git", "-C", str(root), "add", relpath], check=True, capture_output=True, env=env)
        subprocess.run(["git", "-C", str(root), "commit", "-m", "c"], check=True, capture_output=True, env=env)

    @staticmethod
    def _budget(key: str, last_seen: str, *, count: int = 2) -> dict:
        return {"kind": "over-budget", "key": key, "detail": key, "count": count, "first_seen": last_seen, "last_seen": last_seen}

    def test_warning_older_than_file_commit_is_unconfirmed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            self._commit_file(root, "src/a.py", "A = 1\n", "2026-09-09T10:00:00+08:00")
            manifest = bare_manifest(root)
            # 01:00 UTC = 09:00 (+08)，早于文件提交 10:00 (+08) → 记录可能已死
            _write_warning_history(manifest, [self._budget("src/a.py:f", "2026-09-09T01:00:00+00:00")])
            report = hazard_report(manifest)
            self.assertEqual("unconfirmed", report["hazards"][0]["freshness"])

    def test_warning_newer_than_file_commit_is_standing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            self._commit_file(root, "src/a.py", "A = 1\n", "2026-09-09T08:00:00+08:00")
            manifest = bare_manifest(root)
            # 01:30 UTC = 09:30 (+08)，晚于文件提交 08:00 (+08) → 警告针对当前内容
            _write_warning_history(manifest, [self._budget("src/a.py:f", "2026-09-09T01:30:00+00:00")])
            report = hazard_report(manifest)
            self.assertEqual("standing", report["hazards"][0]["freshness"])

    def test_unconfirmed_sorts_after_standing_despite_higher_severity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._repo(root)
            self._commit_file(root, "src/new.py", "A = 1\n", "2026-09-09T08:00:00+08:00")
            self._commit_file(root, "src/old.py", "B = 1\n", "2026-09-09T12:00:00+08:00")
            manifest = bare_manifest(root)
            _write_warning_history(
                manifest,
                [
                    # count 9（severity 更高）但文件 12:00 改过、last_seen 01:00 UTC → unconfirmed
                    self._budget("src/old.py:f", "2026-09-09T01:00:00+00:00", count=9),
                    # count 1 但 last_seen 02:00 UTC = 10:00 (+08) 晚于 08:00 提交 → standing
                    self._budget("src/new.py:g", "2026-09-09T02:00:00+00:00", count=1),
                ],
            )
            report = hazard_report(manifest)
            self.assertEqual("src/new.py", report["hazards"][0]["target"])
            self.assertEqual("standing", report["hazards"][0]["freshness"])
            self.assertEqual("src/old.py", report["hazards"][1]["target"])
            self.assertEqual("unconfirmed", report["hazards"][1]["freshness"])

    def test_git_failure_degrades_to_standing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = bare_manifest(Path(directory))  # 无 git 仓库
            _write_warning_history(manifest, [self._budget("src/a.py:f", "2026-09-09T01:00:00+00:00")])
            report = hazard_report(manifest)
            self.assertEqual("standing", report["hazards"][0]["freshness"])

    def test_pure_freshness_rules(self) -> None:
        earlier = datetime(2026, 9, 9, 1, 0, tzinfo=timezone.utc)
        later = datetime(2026, 9, 9, 2, 0, tzinfo=timezone.utc)
        self.assertEqual("unconfirmed", _warning_freshness(earlier, later))
        self.assertEqual("standing", _warning_freshness(later, earlier))
        self.assertEqual("standing", _warning_freshness(None, later))
        self.assertEqual("standing", _warning_freshness(earlier, None))


class DismissalTests(unittest.TestCase):
    """豁免：审过判定不拆的条目带理由+日落期隐藏，到期自动重现。"""

    @staticmethod
    def _live_pair(target: str = "src/a.py") -> dict:
        return {
            "file": target, "name": "f", "lines": 9,
            "other_file": "src/b.py", "other_name": "g", "other_lines": 9, "match": "相似",
        }

    def test_dismissed_hazard_hidden_until_expiry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = bare_manifest(Path(directory))
            now = datetime(2026, 9, 9, tzinfo=timezone.utc)
            # 查重区是实时扫描：mock 扫描器提供活重复对
            with mock.patch("ag2c.checks.scan_duplicate_pairs", return_value=[self._live_pair()]):
                dismiss_hazard(manifest, "src/a.py", "duplicate", actor="mayor", reason="审过：巧合性相似", now=now)
                report = hazard_report(manifest, now=now + timedelta(days=1))
                self.assertEqual([], report["hazards"])
                self.assertEqual(1, report["dismissed"])
                expired = hazard_report(manifest, now=now + timedelta(days=91))
                self.assertEqual(1, len(expired["hazards"]))
                self.assertEqual(0, expired["dismissed"])

    def test_renewal_replaces_instead_of_stacking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = bare_manifest(Path(directory))
            now = datetime(2026, 9, 9, tzinfo=timezone.utc)
            dismiss_hazard(manifest, "src/a.py", "duplicate", actor="mayor", reason="首次豁免", now=now)
            later = dismiss_hazard(manifest, "src/a.py", "duplicate", actor="mayor", reason="续期", now=now + timedelta(days=30))
            dismissals = load_dismissals(manifest)
            self.assertEqual(1, len(dismissals))
            self.assertEqual(later["expires_at"], dismissals[0]["expires_at"])
            self.assertEqual("续期", dismissals[0]["reason"])

    def test_ledger_event_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = bare_manifest(Path(directory))
            dismiss_hazard(manifest, "src/a.py", "duplicate", actor="mayor", reason="留痕", now=datetime(2026, 9, 9, tzinfo=timezone.utc))
            events = read_events(manifest.ledger_path)
            self.assertEqual("hazard-dismiss", events[-1].get("event_type"))
            self.assertEqual("src/a.py", events[-1].get("payload", {}).get("target"))

    def test_corrupt_dismissals_store_degrades_to_no_dismissals(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = bare_manifest(Path(directory))
            manifest.state_dir.mkdir(parents=True, exist_ok=True)
            (manifest.state_dir / "hazard-dismissals.json").write_text("{broken", encoding="utf-8")
            with mock.patch("ag2c.checks.scan_duplicate_pairs", return_value=[self._live_pair()]):
                report = hazard_report(manifest, now=datetime(2026, 9, 9, tzinfo=timezone.utc))
            self.assertEqual(1, len(report["hazards"]))
            self.assertEqual(0, report["dismissed"])

    def test_rejects_unknown_kind_and_empty_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = bare_manifest(Path(directory))
            with self.assertRaises(AG2CError):
                dismiss_hazard(manifest, "src/a.py", "unknown-kind", actor="a", reason="r")
            with self.assertRaises(AG2CError):
                dismiss_hazard(manifest, "  ", "duplicate", actor="a", reason="r")

    def test_cli_end_to_end(self) -> None:
        """CLI 层全路径：解析 → 分发 → 落盘。t19 教训：每一层都要有自己的测试。"""
        import io
        import os

        from ag2c.cli import main

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "proj"
            write_project(root)
            previous = Path.cwd()
            stdout = io.StringIO()
            try:
                os.chdir(root)
                with mock.patch("sys.stdout", stdout):
                    exit_code = main(["govern", "hazard-dismiss", "tests/support.py", "--kind", "duplicate",
                                      "--actor", "test", "--reason", "CLI 全路径", "--days", "30"])
            finally:
                os.chdir(previous)
            self.assertEqual(0, exit_code)
            from ag2c.config import discover_manifest, load_manifest

            manifest = load_manifest(discover_manifest(root))
            dismissals = load_dismissals(manifest)
            self.assertEqual(1, len(dismissals))
            self.assertEqual("tests/support.py", dismissals[0]["target"])


class DashboardIntegrationTests(unittest.TestCase):
    def _details(self, hazards: list[dict]) -> dict:
        return {"project": {"name": "demo"}, "hazards": {"schema": HAZARD_SCHEMA, "hazards": hazards, "counts": {}}}

    def test_hazard_section_lists_top_five_with_city_language(self) -> None:
        hazards = [
            {"target": f"src/m{i}.py", "kind": "duplicate", "severity": 30, "suggestion": "合并重复实现"} for i in range(6)
        ]
        model = dashboard_model(self._details(hazards), {})
        self.assertEqual(5, len(model["hazards"]))
        self.assertIn("重复代码", model["hazards"][0]["text"])
        self.assertIn("合并重复实现", model["hazards"][0]["text"])

    def test_unresolved_hollow_raises_warn_anomaly(self) -> None:
        hazards = [{"target": "src/ag2c_gui/graph.py", "kind": "hollow", "severity": 40, "suggestion": "补充能捕获该类缺陷的测试", "resolved": False}]
        model = dashboard_model(self._details(hazards), {})
        self.assertTrue(any("测试无效风险" in a["text"] and a["severity"] == "warn" for a in model["anomalies"]))
        self.assertEqual("error", model["hazards"][0]["severity"])

    def test_resolved_hollow_stays_off_the_anomaly_list(self) -> None:
        hazards = [{"target": "src/ag2c/receipts.py", "kind": "hollow", "severity": 40, "suggestion": "补充能捕获该类缺陷的测试", "resolved": True}]
        model = dashboard_model(self._details(hazards), {})
        self.assertFalse(any("测试无效风险" in a["text"] for a in model["anomalies"]))
        self.assertIn("疑似已修复", model["hazards"][0]["text"])

    def test_missing_hazards_section_degrades_silently(self) -> None:
        model = dashboard_model({"project": {"name": "demo"}}, {})
        self.assertEqual([], model["hazards"])
        self.assertEqual([], model["anomalies"])

    def test_unconfirmed_hazard_is_labeled_for_review(self) -> None:
        hazards = [
            {"target": "src/ag2c/govern.py", "kind": "duplicate", "severity": 32, "suggestion": "合并重复实现", "freshness": "unconfirmed"}
        ]
        model = dashboard_model(self._details(hazards), {})
        self.assertIn("待复核", model["hazards"][0]["text"])


class LiveDuplicateScanTests(unittest.TestCase):
    """不 mock 的全链路：真实夹具项目 + 真实文件，验证扫描接线与化石消失。"""

    def test_real_pair_listed_and_fossil_dropped(self) -> None:
        from ag2c.config import load_manifest

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "proj"
            write_project(root)
            # 两个房间里各写一个结构一致的 4 行同名函数（现行规则必命中）
            body = "    x = a + b\n    y = x * 2\n    z = y - 1\n    return z\n"
            (root / "src" / "api" / "service.py").write_text(f"def helper(a, b):\n{body}", encoding="utf-8")
            (root / "src" / "worker" / "job.py").write_text(f"def helper(a, b):\n{body}", encoding="utf-8")
            manifest = load_manifest(root / ".ag2c" / "manifest.json")
            # 化石：历史里一条现行规则不再复现的旧记录（撞名 1 行函数）
            _write_warning_history(
                manifest,
                [{"kind": "possible-duplicate", "key": "src/ag2c/cli.py:main", "count": 4,
                  "detail": "同名函数 main（src/ag2c/cli.py）与 src/ag2c_gui/imgui_tray.py 参数数相同"}],
            )
            report = hazard_report(manifest)
            duplicates = [h for h in report["hazards"] if h["kind"] == "duplicate"]
            self.assertEqual(1, len(duplicates))
            self.assertIn("helper", duplicates[0]["detail"])
            self.assertEqual("standing", duplicates[0]["freshness"])
            self.assertEqual("live-scan", duplicates[0]["evidence"]["store"])
            # 化石（main 撞名）不上榜
            self.assertFalse(any("main" in h["detail"] for h in duplicates))

    def test_test_only_pairs_stay_off_the_demolition_queue(self) -> None:
        """双测试文件的相似对不进拆迁队列（测试镜像结构是表驱动常态）。

        夹具的 governed_roots 只含 src，故用 test_ 前缀文件放进 src——
        没有过滤器时这对必命中（同形 4 行以上），测试才不是空转。"""
        from ag2c.config import load_manifest

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "proj"
            write_project(root)
            body = "    x = a + b\n    y = x * 2\n    z = y - 1\n    return z\n"
            (root / "src" / "test_a.py").write_text(f"def check_it(a, b):\n{body}", encoding="utf-8")
            (root / "src" / "test_b.py").write_text(f"def check_it(a, b):\n{body}", encoding="utf-8")
            manifest = load_manifest(root / ".ag2c" / "manifest.json")
            report = hazard_report(manifest)
            self.assertEqual([], [h for h in report["hazards"] if h["kind"] == "duplicate"])


if __name__ == "__main__":
    unittest.main()
