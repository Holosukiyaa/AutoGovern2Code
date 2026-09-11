"""token 会计：治理成本折算成钱的聚合逻辑测试。"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import bootstrap

from ag2c.token import COST_REPORT_SCHEMA, DEFAULTS, TOKEN_SCHEMA, cost_report, token_report
from ag2c_gui.dashboard import dashboard_model

from support import bare_manifest

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


def _write_ledger(manifest, events: list[dict]) -> None:
    """造一条合法哈希链账本（append_event 无法控制 occurred_at，月度分桶测试需要历史时间）。"""
    from ag2c.ledger import EVENT_SCHEMA, ZERO_DIGEST
    from ag2c.util import canonical_json, digest_json

    previous = ZERO_DIGEST
    lines = []
    for index, event in enumerate(events, 1):
        record = {
            "schema": EVENT_SCHEMA,
            "sequence": index,
            "occurred_at": event.get("occurred_at") or NOW.isoformat(),
            "event_type": event["event_type"],
            "previous_digest": previous,
            "payload": event.get("payload", {}),
        }
        record["event_digest"] = digest_json(record)
        previous = record["event_digest"]
        lines.append(canonical_json(record))
    manifest.ledger_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _started(task_id: str, at: datetime | None = None) -> dict:
    event = {"event_type": "task-started", "payload": {"task_id": task_id}}
    if at is not None:
        event["occurred_at"] = at.isoformat()
    return event


def _verified(task_id: str, files: int, at: datetime | None = None) -> dict:
    event = {"event_type": "task-verification", "payload": {"task_id": task_id, "changed_paths": [f"f{i}.py" for i in range(files)]}}
    if at is not None:
        event["occurred_at"] = at.isoformat()
    return event


class TokenReportTests(unittest.TestCase):
    def test_empty_ledger_yields_zero_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = bare_manifest(Path(directory))
            report = token_report(manifest, now=NOW)
            self.assertEqual(TOKEN_SCHEMA, report["schema"])
            self.assertEqual(0, report["tasks"])
            self.assertEqual(0, report["tokens"]["total"])
            self.assertEqual(0.0, report["cost_usd"])
            self.assertEqual([], report["top_rework"])

    def test_missing_ledger_degrades_to_zero_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = bare_manifest(Path(directory))  # 不创建账本文件
            report = token_report(manifest, now=NOW)
            self.assertEqual(0, report["tokens"]["total"])

    def test_aggregation_math(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = bare_manifest(Path(directory))
            _write_ledger(
                manifest,
                [
                    _started("task-a"),
                    _started("task-b"),
                    _verified("task-a", files=2),
                    _verified("task-a", files=3),  # 返工：第二次 verify
                    _verified("task-b", files=1),
                ],
            )
            report = token_report(manifest, now=NOW)
            self.assertEqual(2, report["tasks"])
            self.assertEqual(3, report["verify_runs"])
            self.assertEqual(1, report["rework_runs"])
            expected_verify = (2000 + 300 * 2) + (2000 + 300 * 3) + (2000 + 300 * 1)
            self.assertEqual(2 * 3000, report["tokens"]["session_tax"])
            self.assertEqual(2 * 4000, report["tokens"]["guidance"])
            self.assertEqual(expected_verify, report["tokens"]["verify"])
            total = 2 * 3000 + 2 * 4000 + expected_verify
            self.assertEqual(total, report["tokens"]["total"])
            self.assertAlmostEqual(total / 1_000_000 * 2.0, report["cost_usd"], places=6)
            self.assertEqual({"task": "task-a", "verify_runs": 2}, report["top_rework"][0])

    def test_month_bucket_only_counts_current_month(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = bare_manifest(Path(directory))
            last_month = datetime(2026, 8, 20, tzinfo=timezone.utc)
            _write_ledger(
                manifest,
                [
                    _started("old-task", at=last_month),
                    _verified("old-task", files=5, at=last_month),
                    _started("new-task"),  # NOW = 2026-09-09
                    _verified("new-task", files=1),
                ],
            )
            report = token_report(manifest, now=NOW)
            self.assertEqual(2, report["tasks"])  # 累计含上月
            expected_month = 1 * (3000 + 4000) + (2000 + 300 * 1)
            self.assertEqual(expected_month, report["month_tokens"])

    def test_policy_token_section_overrides_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = bare_manifest(Path(directory))
            manifest.policy_path.write_text(
                json.dumps({"token": {"price_per_million_usd": 10.0, "session_tax_tokens": 100}}),
                encoding="utf-8",
            )
            _write_ledger(manifest, [_started("task-a")])
            report = token_report(manifest, now=NOW)
            self.assertEqual(100.0, report["config"]["session_tax_tokens"])
            self.assertEqual(4000.0, report["config"]["guidance_tokens_per_task"])  # 未覆盖的用默认
            expected = int(100 + 4000)
            self.assertAlmostEqual(expected / 1_000_000 * 10.0, report["cost_usd"], places=6)

    def test_corrupt_policy_falls_back_to_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = bare_manifest(Path(directory))
            manifest.policy_path.write_text("{broken", encoding="utf-8")
            _write_ledger(manifest, [_started("task-a")])
            report = token_report(manifest, now=NOW)
            self.assertEqual(DEFAULTS["session_tax_tokens"], report["config"]["session_tax_tokens"])


class CostReportTests(unittest.TestCase):
    def test_empty_and_three_legs(self) -> None:
        from ag2c.errors import AG2CError
        from ag2c.tasks import cost_self_report

        with tempfile.TemporaryDirectory() as directory:
            manifest = bare_manifest(Path(directory))
            empty = cost_report(manifest, now=NOW)
            self.assertEqual(COST_REPORT_SCHEMA, empty["schema"])
            self.assertEqual("MTok", empty["unit"])
            self.assertIsNone(empty["efficiency"]["rounds_per_task"])
            self.assertTrue(empty["economy"]["self_report"]["inferred"])
            self.assertNotIn("cost_usd", empty)
            start = datetime(2026, 9, 9, 10, 0, tzinfo=timezone.utc)
            done = datetime(2026, 9, 9, 11, 0, tzinfo=timezone.utc)
            usage = {"model": "deepseek-v4-flash", "input": 1_000_000, "output": 500_000, "source": "regulator-api"}
            inferred = {"source": "INFERRED", "estimated_tokens": {"model": "grok", "input": 100, "output": 50}}
            _write_ledger(
                manifest,
                [
                    {"event_type": "task-started", "occurred_at": start.isoformat(), "payload": {"task_id": "a"}},
                    {"event_type": "task-verification", "payload": {"task_id": "a", "passed": True, "regulator": {"outcome": "passed", "usage": usage}}},
                    {"event_type": "task-completed", "occurred_at": done.isoformat(), "payload": {"task_id": "a", "kind": "fix", "cost_self_report": inferred}},
                    {"event_type": "task-started", "payload": {"task_id": "b"}},
                    {"event_type": "task-verification", "payload": {"task_id": "b", "passed": False, "regulator": {"outcome": "rejected"}}},
                ],
            )
            report = cost_report(manifest, now=NOW)
        self.assertEqual(1.0, report["efficiency"]["rounds_per_task"])
        self.assertEqual(3600.0, report["efficiency"]["mean_task_seconds"])
        self.assertEqual(0.5, report["efficiency"]["verify_failure_rate"])
        self.assertEqual(1.5, report["economy"]["regulator"]["mtok"])
        self.assertEqual(150, report["economy"]["self_report"]["total"])
        self.assertEqual(1.0, report["effectiveness"]["first_pass_rate"])
        self.assertEqual(0.5, report["effectiveness"]["regulator_reject_rate"])
        self.assertEqual(1, report["effectiveness"]["post_delivery_fixes"])
        self.assertIsNone(cost_self_report())
        payload = cost_self_report(sessions=2, estimated_tokens={"model": "grok", "input": 1, "output": 2})
        self.assertEqual("INFERRED", payload["source"])
        with self.assertRaises(AG2CError):
            cost_self_report(sessions=True)  # type: ignore[arg-type]


class DashboardTokenTests(unittest.TestCase):
    def test_token_section_renders_cost_and_rework(self) -> None:
        details = {
            "project": {"name": "demo"},
            "token": {
                "schema": TOKEN_SCHEMA,
                "month_cost_usd": 0.12,
                "month_tokens": 60000,
                "cost_usd": 1.5,
                "top_rework": [{"task": "task-a", "verify_runs": 4}],
            },
        }
        model = dashboard_model(details, {})
        texts = [line["text"] for line in model["token"]]
        self.assertTrue(any("$0.12" in text and "60,000" in text for text in texts))
        self.assertTrue(any("task-a" in text and "4" in text for text in texts))

    def test_missing_token_section_degrades_silently(self) -> None:
        model = dashboard_model({"project": {"name": "demo"}}, {})
        self.assertEqual([], model["token"])


if __name__ == "__main__":
    unittest.main()
