"""Tests for task helpers (finish hints)."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import bootstrap

from ag2c.model import Manifest
from ag2c.tasks import _finish_hints

from support import git_project, record_census, write_project


def _bare_manifest(root: Path) -> Manifest:
    return Manifest(
        path=root / "manifest.json",
        project_id="test-proj",
        project_root=root,
        targets=[],
        ledger_path=root / "ledger.jsonl",
        policy_path=root / "policy.json",
        state_dir=root / "state",
    )


class FinishHintTests(unittest.TestCase):
    def test_pending_items_produce_settle_hint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, policy = write_project(Path(directory))
            pending = {"items": [{"kind": "stale-knowledge", "path": "knowledge.worker"}]}
            hints = _finish_hints(manifest, policy, pending)
            self.assertTrue(any("govern settle" in hint for hint in hints), hints)

    def test_unreviewed_rooms_produce_census_hint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, policy = write_project(Path(directory))
            # No census records at all: every room reports freshness "never".
            hints = _finish_hints(manifest, policy, {"items": []})
            self.assertTrue(any("govern census --record" in hint for hint in hints), hints)

    def test_clean_project_produces_no_hints(self) -> None:
        from ag2c.model import Coverage, Policy

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "state").mkdir()
            manifest = _bare_manifest(root)
            # No targets -> no households -> nothing stale; empty pending.
            policy = Policy(
                path=root / "policy.json",
                cards=(),
                relations=(),
                contracts=(),
                checkers=(),
                coverage=Coverage(level="none", strategy="conservative", managed_by="project", areas=()),
                household_required=False,
            )
            hints = _finish_hints(manifest, policy, {"items": []})
            self.assertEqual([], hints)


class VerificationEvidenceTests(unittest.TestCase):
    """_verification_evidence_valid tolerates payload keys it does not know."""

    def _fixture(self, root: Path, *, extra: dict | None = None):
        from ag2c.ledger import append_event
        from ag2c.tasks import _verification_evidence_valid

        manifest = _bare_manifest(root)
        task = {"id": "t-x"}
        check = append_event(
            manifest.ledger_path,
            "check-run",
            {
                "task_id": "t-x",
                "results": [{"id": "c1", "stage": "floor", "status": "passed", "exit_code": 0}],
                "slice_digest": "s",
            },
        )
        payload = {
            "attempt": 1,
            "occurred_at": "2026-09-09T00:00:00+00:00",
            "passed": True,
            "changed_paths": ["app:src/x.py"],
            "change_digest": "d",
            "slice_digest": "s",
            "route_state": "conservative",
            "route": {"state": "conservative"},
            "route_cards": [],
            "checker_results": [{"id": "c1", "stage": "floor", "status": "passed", "exit_code": 0}],
            "acceptance": "ok",
            "check_ledger_event_digest": check["event_digest"],
        }
        event = append_event(
            manifest.ledger_path,
            "task-verification",
            {"task_id": "t-x", **payload, **(extra or {})},
        )
        verification = {**payload, "ledger_event_digest": event["event_digest"]}
        return manifest, task, verification, _verification_evidence_valid

    def test_unknown_extension_keys_tolerated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, task, verification, valid = self._fixture(
                Path(directory), extra={"future-field": {"new": True}}
            )
            self.assertTrue(valid(manifest, task, verification))

    def test_checker_durations_field_tolerated(self) -> None:
        """checker_durations 等信息性顶层字段不参与证据绑定：旧版 finish 也能验证新版记录。"""
        with tempfile.TemporaryDirectory() as directory:
            manifest, task, verification, valid = self._fixture(
                Path(directory), extra={"checker_durations": {"c1": 123}}
            )
            self.assertTrue(valid(manifest, task, verification))

    def test_checker_results_stable_keys_still_bound(self) -> None:
        """稳定键（id/stage/status/exit_code）仍精确绑定：篡改 status 必败。"""
        with tempfile.TemporaryDirectory() as directory:
            manifest, task, verification, valid = self._fixture(Path(directory))
            verification["checker_results"] = [
                {"id": "c1", "stage": "floor", "status": "failed", "exit_code": 0, "duration_ms": 123}
            ]
            self.assertFalse(valid(manifest, task, verification))

    def test_tampered_known_key_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, task, verification, valid = self._fixture(
                Path(directory), extra={"future-field": {"new": True}}
            )
            verification["change_digest"] = "tampered"
            self.assertFalse(valid(manifest, task, verification))

    def test_regulator_verdict_is_bound(self) -> None:
        # agent-review 落地后 regulator 是已知键：payload 与任务记录必须一致
        with tempfile.TemporaryDirectory() as directory:
            manifest, task, verification, valid = self._fixture(
                Path(directory), extra={"regulator": {"outcome": "passed"}}
            )
            verification["regulator"] = {"outcome": "passed"}
            self.assertTrue(valid(manifest, task, verification))
            verification["regulator"] = {"outcome": "rejected"}
            self.assertFalse(valid(manifest, task, verification))

    def test_missing_known_key_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, task, verification, valid = self._fixture(Path(directory))
            verification["changed_paths"] = ["app:src/other.py"]
            self.assertFalse(valid(manifest, task, verification))


class AutoRefreshTests(unittest.TestCase):
    """并行税自愈：canonical 增量与任务路径不相交时，verify/finish 自动 refresh 而非报错。"""

    def _project(self, tmp: str) -> Path:
        """生产拓扑夹具：enroll_project 外部存储 + gated 夹具 policy。

        仓内 .ag2c 夹具的 state/ledger 是 per-checkout 的，finish 的 receipt 验证
        会找不到文件；真实项目是 enroll 的外部存储（canonical 与 worktree 共享）。
        """
        import os
        import shutil

        from ag2c.enrollment import enroll_project

        base = Path(tmp)
        root = git_project(base / "proj")
        # 夹具房间文件（write_project 只写在 scratch 里做 policy 母本，项目树要自己带）
        (root / "src" / "api").mkdir(parents=True)
        (root / "src" / "worker").mkdir(parents=True)
        (root / "src" / "api" / "service.py").write_text("VALUE = 'api'\n", encoding="utf-8")
        (root / "src" / "worker" / "job.py").write_text("VALUE = 'worker'\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "--all"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(root), "commit", "-m", "rooms"], check=True, capture_output=True)
        with mock.patch.dict(os.environ, {"AG2C_DATA_ROOT": str(base / "ag2c-data")}, clear=False):
            result = enroll_project(root, skill_root=base / "skills", harnesses=("agents",))
        store = Path(result["store"])
        scratch = base / "scratch"
        write_project(scratch, gated=True)
        shutil.copy2(scratch / ".ag2c" / "policy.json", store / "policy.json")
        # enroll 保持工作树干净（外部存储拓扑），无需提交；canonical 干净即可开任务
        return root

    def _start(self, root: Path):
        from ag2c.tasks import start_task

        portrait = (
            "Done looks like: 服务函数返回值变更。Surfaces: verify 通过。"
            "Out of result: 不动其他模块。验证层: 机器验证 tests 套件全绿，输出片段进 finish proof。无加料。"
        )
        return start_task(
            root,
            goal="change",
            path_specs=["app:src/api/service.py"],
            contract_specs=[],
            portrait=portrait,
            worktree_root=root.parent / "worktrees",
        )

    def _touch_task_file(self, worktree: Path) -> None:
        service = worktree / "src" / "api" / "service.py"
        service.write_text(service.read_text(encoding="utf-8") + "# touched by task\n", encoding="utf-8")

    def _diverge_canonical(self, root: Path, rel: str) -> None:
        target = root / rel
        target.write_text(target.read_text(encoding="utf-8") + "# other lane\n", encoding="utf-8")
        # 只提交目标文件 + --no-verify：模拟另一条泳道的 finish 合并（merge 不触发 pre-commit）
        subprocess.run(["git", "-C", str(root), "add", "--", rel], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(root), "commit", "--no-verify", "-m", "other lane"], check=True, capture_output=True)

    def _task_record(self, root: Path, task_id: str) -> dict:
        from ag2c.config import discover_manifest, load_manifest

        manifest = load_manifest(discover_manifest(root), project_root=root)
        return json.loads((manifest.state_dir / "tasks" / f"{task_id}.json").read_text(encoding="utf-8"))

    def test_start_surfaces_ai_additions(self) -> None:
        from ag2c.tasks import start_task

        with tempfile.TemporaryDirectory() as tmp:
            root = self._project(tmp)
            started = self._start(root)
            # 夹具画像声明了无加料 → 空清单
            self.assertEqual("", started["ai_additions"])

            started2 = start_task(
                root,
                goal="g2",
                path_specs=["app:src/worker/job.py"],
                contract_specs=[],
                portrait=(
                    "Done looks like: 任务函数变更。验证层: 机器验证 tests 套件全绿。"
                    "Inferences: INFERRED 用户说的任务指 worker/job.py。"
                ),
                worktree_root=root.parent / "worktrees",
            )
            self.assertIn("INFERRED 用户说的任务", started2["ai_additions"])

    def test_verify_auto_refreshes_on_disjoint_divergence(self) -> None:
        from ag2c.tasks import verify_task

        with tempfile.TemporaryDirectory() as tmp:
            root = self._project(tmp)
            task = self._start(root)
            worktree = Path(task["worktree"]["path"])
            self._touch_task_file(worktree)
            record_census(worktree)
            self._diverge_canonical(root, "src/worker/job.py")
            report = verify_task(worktree)
            self.assertTrue(report["passed"])
            self.assertEqual("verified", report["state"])
            # refresh 的干预记录存在，且 worktree 已含 canonical 增量
            record = self._task_record(root, task["id"])
            self.assertIn("source-refreshed", [item["kind"] for item in record["interventions"]])
            self.assertIn("# other lane", (worktree / "src" / "worker" / "job.py").read_text(encoding="utf-8"))
            self.assertIn("# touched by task", (worktree / "src" / "api" / "service.py").read_text(encoding="utf-8"))

    def test_verify_still_refuses_overlapping_divergence(self) -> None:
        from ag2c.errors import AG2CError
        from ag2c.tasks import verify_task

        with tempfile.TemporaryDirectory() as tmp:
            root = self._project(tmp)
            task = self._start(root)
            worktree = Path(task["worktree"]["path"])
            self._touch_task_file(worktree)
            record_census(worktree)
            self._diverge_canonical(root, "src/api/service.py")  # 与任务路径相交
            with self.assertRaisesRegex(AG2CError, "canonical HEAD changed"):
                verify_task(worktree)
            record = self._task_record(root, task["id"])
            self.assertIn("canonical-head-diverged", [item["kind"] for item in record["interventions"]])

    def test_finish_auto_recovers_on_disjoint_divergence(self) -> None:
        from ag2c.tasks import finish_task, verify_task

        with tempfile.TemporaryDirectory() as tmp:
            root = self._project(tmp)
            task = self._start(root)
            worktree = Path(task["worktree"]["path"])
            self._touch_task_file(worktree)
            record_census(worktree)
            self.assertTrue(verify_task(worktree)["passed"])
            # verify 之后、finish 之前，另一条泳道合并了不相干的改动
            self._diverge_canonical(root, "src/worker/job.py")
            result = finish_task(root, task["id"], message="实现服务函数变更", proof="机器验证：夹具 checker 全绿")
            self.assertEqual("completed", result["state"])
            # 内联重验确实发生：两次验证记录，第二次绑定新 HEAD
            record = self._task_record(root, task["id"])
            self.assertEqual(2, len(record["verifications"]))
            self.assertTrue(all(item["passed"] for item in record["verifications"]))
            self.assertIn("# touched by task", (root / "src" / "api" / "service.py").read_text(encoding="utf-8"))
            self.assertIn("# other lane", (root / "src" / "worker" / "job.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
