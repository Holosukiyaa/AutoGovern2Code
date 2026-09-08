"""9.11 随机抽查计划：生成/持久化/确认/间隔随机/AI 上下文不可见。"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from ag2c.audit import (
    AUDIT_STATE_SCHEMA,
    MAX_INTERVAL_DAYS,
    MIN_INTERVAL_DAYS,
    _state_path,
    acknowledge,
    audit_status,
    maybe_generate_plan,
)
from ag2c.config import load_policy
from ag2c.model import Manifest, Target

T0 = datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)

ROOMS = ["knowledge.a", "knowledge.b", "knowledge.c", "knowledge.d", "knowledge.e"]


def _manifest(root: Path) -> Manifest:
    return Manifest(
        path=root / "state" / "manifest.json",
        project_id="test-proj",
        project_root=root,
        targets=[Target(target_id="app", path=".", governed_roots=("src",), excludes=())],
        ledger_path=root / "state" / "ledger.jsonl",
        policy_path=root / "state" / "policy.json",
        state_dir=root / "state",
    )


def _policy(manifest: Manifest, *, rooms: list[str] | None = None) -> object:
    cards = [
        {
            "id": room_id,
            "type": "knowledge",
            "title": room_id,
            "summary": "room",
            "jurisdiction": {
                "span": "folder",
                "grain": "subtree",
                "contract": "none",
                "decider": "none",
                "capability": "room",
                "meaning": "named",
                "implementation": "src.exploring",
                "status": "current",
                "entrypoints": [],
            },
            "scopes": [{"target": "app", "include": [f"src/{room_id}/**"], "ownership": "reference"}],
        }
        for room_id in (rooms if rooms is not None else ROOMS)
    ]
    cards.append({"id": "knowledge.flat", "type": "knowledge", "title": "f", "summary": "s"})  # no jurisdiction: not a room
    cards.append(
        {
            "id": "floor.app",
            "type": "floor",
            "title": "f",
            "summary": "s",
            "scopes": [{"target": "app", "include": ["src/**"], "ownership": "primary"}],
            "checkers": ["check.noop"],
        }
    )  # load_policy requires a floor card with a primary scope and a floor checker
    checkers = [{"id": "check.noop", "command": ["python", "-c", "pass"], "stage": "floor"}]
    manifest.policy_path.parent.mkdir(parents=True, exist_ok=True)
    manifest.policy_path.write_text(
        json.dumps({"schema": "ag2c.policy.v1", "cards": cards, "checkers": checkers}), encoding="utf-8"
    )
    return load_policy(manifest)


def _receipts(manifest: Manifest, count: int = 3) -> list[str]:
    directory = manifest.path.parent / "receipts"
    directory.mkdir(parents=True, exist_ok=True)
    ids = []
    for index in range(count):
        task_id = f"t{index:03d}"
        (directory / f"{task_id}.json").write_text("{}", encoding="utf-8")
        ids.append(task_id)
    return ids


class PlanGenerationTests(unittest.TestCase):
    def test_first_call_generates_plan_immediately(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = _manifest(Path(tmp))
            policy = _policy(manifest)
            receipts = _receipts(manifest)
            plan = maybe_generate_plan(manifest, policy, now=T0)
            self.assertIsNotNone(plan)
            room_items = [i for i in plan["items"] if i["kind"] == "room-card"]
            receipt_items = [i for i in plan["items"] if i["kind"] == "receipt"]
            self.assertGreaterEqual(len(room_items), 1)
            self.assertLessEqual(len(room_items), 3)
            self.assertTrue({i["id"] for i in room_items} <= set(ROOMS))
            self.assertEqual(1, len(receipt_items))
            self.assertIn(receipt_items[0]["id"], receipts)
            self.assertFalse(plan["acknowledged"])
            # 计划落盘在 state 目录（数据目录，非仓库）
            state = json.loads(_state_path(manifest).read_text(encoding="utf-8"))
            self.assertEqual(AUDIT_STATE_SCHEMA, state["schema"])
            self.assertEqual(plan["id"], state["plan"]["id"])

    def test_active_plan_returned_without_regeneration(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = _manifest(Path(tmp))
            policy = _policy(manifest)
            _receipts(manifest)
            first = maybe_generate_plan(manifest, policy, now=T0)
            second = maybe_generate_plan(manifest, policy, now=T0 + timedelta(hours=6))
            self.assertEqual(first["id"], second["id"])

    def test_no_plan_before_next_plan_at(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = _manifest(Path(tmp))
            policy = _policy(manifest)
            maybe_generate_plan(manifest, policy, now=T0)
            self.assertTrue(acknowledge(manifest, now=T0))
            # 确认后间隔内不生成新计划
            self.assertIsNone(maybe_generate_plan(manifest, policy, now=T0 + timedelta(days=1)))

    def test_plan_regenerates_after_window(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = _manifest(Path(tmp))
            policy = _policy(manifest)
            first = maybe_generate_plan(manifest, policy, now=T0)
            acknowledge(manifest, now=T0)
            later = maybe_generate_plan(manifest, policy, now=T0 + timedelta(days=MAX_INTERVAL_DAYS + 1))
            self.assertIsNotNone(later)
            self.assertNotEqual(first["id"], later["id"])

    def test_interval_within_bounds(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = _manifest(Path(tmp))
            policy = _policy(manifest)
            maybe_generate_plan(manifest, policy, now=T0)
            acknowledge(manifest, now=T0)
            state = json.loads(_state_path(manifest).read_text(encoding="utf-8"))
            next_at = datetime.fromisoformat(state["next_plan_at"])
            delta = (next_at - T0).days
            self.assertGreaterEqual(delta, MIN_INTERVAL_DAYS)
            self.assertLessEqual(delta, MAX_INTERVAL_DAYS)

    def test_empty_project_generates_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = _manifest(Path(tmp))
            policy = _policy(manifest, rooms=[])  # 无房间卡、无回执
            self.assertIsNone(maybe_generate_plan(manifest, policy, now=T0))

    def test_corrupt_state_file_tolerated(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = _manifest(Path(tmp))
            _state_path(manifest).parent.mkdir(parents=True, exist_ok=True)
            _state_path(manifest).write_text("not json", encoding="utf-8")
            policy = _policy(manifest)
            plan = maybe_generate_plan(manifest, policy, now=T0)
            self.assertIsNotNone(plan)


class AcknowledgeTests(unittest.TestCase):
    def test_acknowledge_flow(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = _manifest(Path(tmp))
            policy = _policy(manifest)
            maybe_generate_plan(manifest, policy, now=T0)
            self.assertTrue(acknowledge(manifest, actor="tester", now=T0 + timedelta(days=1)))
            state = json.loads(_state_path(manifest).read_text(encoding="utf-8"))
            self.assertTrue(state["plan"]["acknowledged"])
            self.assertEqual("tester", state["plan"]["acknowledged_by"])
            self.assertIsNotNone(state["last_ack_at"])
            # 重复确认幂等
            self.assertFalse(acknowledge(manifest, now=T0 + timedelta(days=1)))

    def test_acknowledge_without_plan_is_false(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = _manifest(Path(tmp))
            self.assertFalse(acknowledge(manifest, now=T0))


class StatusTests(unittest.TestCase):
    def test_days_since_none_before_first_ack(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = _manifest(Path(tmp))
            policy = _policy(manifest)
            status = audit_status(manifest, policy, now=T0)
            self.assertIsNone(status["days_since"])
            self.assertTrue(status["pending"])  # 首次即生成计划

    def test_days_since_counts_from_ack(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = _manifest(Path(tmp))
            policy = _policy(manifest)
            maybe_generate_plan(manifest, policy, now=T0)
            acknowledge(manifest, now=T0)
            # +1 天必然在最小间隔（2 天）之内：不会生成新计划
            status = audit_status(manifest, policy, now=T0 + timedelta(days=1))
            self.assertEqual(1, status["days_since"])
            self.assertEqual([], status["pending"])  # 已确认，无待办

    def test_due_flag_after_due_at(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = _manifest(Path(tmp))
            policy = _policy(manifest)
            plan = maybe_generate_plan(manifest, policy, now=T0)
            due_at = datetime.fromisoformat(plan["due_at"])
            before = audit_status(manifest, policy, now=T0)
            self.assertFalse(before["due"])
            after = audit_status(manifest, policy, now=due_at + timedelta(hours=1))
            self.assertTrue(after["due"])


class AiInvisibilityTests(unittest.TestCase):
    """抽查计划不得出现在任何 AI 可见上下文：MCP 工具、INSTRUCTIONS、verify 报告。"""

    def test_no_mcp_tool_exposes_audit(self) -> None:
        from ag2c.mcp_server import tool_defs

        for tool in tool_defs():
            self.assertNotIn("audit", tool["name"].lower())

    def test_mcp_server_does_not_import_audit_module(self) -> None:
        source = (Path(__file__).resolve().parent.parent / "src" / "ag2c" / "mcp_server.py").read_text(encoding="utf-8")
        self.assertNotIn("ag2c.audit", source)
        self.assertNotIn("from .audit", source)
        self.assertNotIn("audit-state", source)

    def test_verify_path_does_not_import_audit_module(self) -> None:
        source = (Path(__file__).resolve().parent.parent / "src" / "ag2c" / "checks.py").read_text(encoding="utf-8")
        self.assertNotIn("ag2c.audit", source)
        self.assertNotIn("from .audit", source)

    def test_audit_state_lives_outside_repo_files(self) -> None:
        """计划文件在 state 目录（数据目录），不是仓库受治理文件。"""
        with TemporaryDirectory() as tmp:
            manifest = _manifest(Path(tmp))
            policy = _policy(manifest)
            maybe_generate_plan(manifest, policy, now=T0)
            self.assertTrue(str(_state_path(manifest)).startswith(str(manifest.path.parent)))


if __name__ == "__main__":
    unittest.main()
