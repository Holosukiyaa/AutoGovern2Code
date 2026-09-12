"""provides 证据锚：锚对通过 / 锚错 apply 拒绝 / 存量普查告警 / 降级跳过。"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import bootstrap

from ag2c.anchors import ANCHOR_WARNING_KIND, anchor_violations, provides_anchor_warnings
from ag2c.checks import run_checks
from ag2c.config import load_manifest, load_policy
from ag2c.errors import AG2CError
from ag2c.govern import apply_change
from ag2c.index import build_index
from ag2c.slicer import compile_slice

from support import record_census, write_project


def _write_module(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


class AnchorViolationTests(unittest.TestCase):
    def test_anchored_provides_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_module(root, "src/mod.py", "CONST = 1\n\n\ndef helper():\n    return CONST\n\n\nclass Widget:\n    pass\n")
            self.assertEqual([], anchor_violations(root, ["helper 工具函数", "Widget 组件", "CONST 常量"], ["src/mod.py"]))

    def test_unanchored_provides_are_reported_verbatim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_module(root, "src/mod.py", "def helper():\n    return 1\n")
            bad = anchor_violations(root, ["helper 存在", "此模块提供 time_travel 能力"], ["src/mod.py"])
            self.assertEqual(["此模块提供 time_travel 能力"], bad)

    def test_non_python_room_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_module(root, "docs/guide.md", "# guide\n")
            self.assertEqual([], anchor_violations(root, ["任意散文"], ["docs/guide.md"]))

    def test_missing_or_empty_references_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual([], anchor_violations(root, ["任意散文"], []))
            self.assertEqual([], anchor_violations(root, [], ["src/mod.py"]))

    def test_ast_parse_failure_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_module(root, "src/broken.py", "def broken(:\n    pass\n")
            self.assertEqual([], anchor_violations(root, ["任意散文"], ["src/broken.py"]))

    def test_missing_reference_file_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual([], anchor_violations(root, ["任意散文"], ["src/gone.py"]))


class ApplyRejectionTests(unittest.TestCase):
    def _project(self, root: Path):
        manifest, policy = write_project(root)
        subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
        return manifest, policy

    def test_apply_rejects_unanchored_provides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._project(root)
            with self.assertRaisesRegex(AG2CError, "provides 锚定失败"):
                    apply_change(
                        root,
                        action="add",
                        kind="card",
                        card_id="knowledge.api-v2",
                        actor="tester",
                        reason="add card",
                        title="API v2",
                        summary="test card",
                        include=["src/api/service.py"],
                        provides=["此模块提供 time_travel 能力"],
                    )

    def test_apply_accepts_anchored_provides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._project(root)
            result = apply_change(
                root,
                action="add",
                kind="card",
                card_id="knowledge.api-v2",
                actor="tester",
                reason="add card",
                title="API v2",
                summary="test card",
                include=["src/api/service.py"],
                provides=["VALUE 常量"],
            )
            self.assertEqual("knowledge.api-v2", result["id"])

    def test_update_without_provides_keeps_legacy_card_unblocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._project(root)
            # 存量卡：直接写坏 provides（绕过 apply），模拟迁移期前的遗产。
            policy_path = root / ".ag2c" / "policy.json"
            raw = json.loads(policy_path.read_text(encoding="utf-8"))
            for card in raw["cards"]:
                if card.get("id") == "knowledge.worker":
                    card["provides"] = ["此模块提供 time_travel 能力"]
            policy_path.write_text(json.dumps(raw), encoding="utf-8")
            # 不追改 provides 的 update 不被锚校验拦截（迁移期）。
            # 注意 apply 会把 references 重写为 --include，故显式传文件路径。
            result = apply_change(
                root,
                action="update",
                kind="card",
                card_id="knowledge.worker",
                actor="tester",
                reason="retitle only",
                title="Worker 导航",
                include=["src/worker/job.py"],
            )
            self.assertEqual("knowledge.worker", result["id"])


class CensusWarningTests(unittest.TestCase):
    def _gated_project_with_bad_provides(self, root: Path):
        write_project(root, gated=True)
        policy_path = root / ".ag2c" / "policy.json"
        raw = json.loads(policy_path.read_text(encoding="utf-8"))
        for card in raw["cards"]:
            if card.get("id") == "knowledge.worker":
                card["provides"] = ["此模块提供 time_travel 能力"]
        policy_path.write_text(json.dumps(raw), encoding="utf-8")
        manifest = load_manifest(root / ".ag2c" / "manifest.json")
        policy = load_policy(manifest)
        build_index(manifest, policy)
        record_census(root)
        return manifest, policy

    def test_existing_card_warns_at_census(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, policy = self._gated_project_with_bad_provides(root)
            warnings = provides_anchor_warnings(manifest, policy)
            self.assertEqual(["knowledge.worker"], [w["key"] for w in warnings])
            self.assertEqual(ANCHOR_WARNING_KIND, warnings[0]["kind"])
            self.assertIn("time_travel", warnings[0]["detail"])

            from ag2c.households import census_report

            report = census_report(manifest, policy)
            self.assertEqual(["knowledge.worker"], [w["key"] for w in report["anchor_warnings"]])

    def test_run_checks_records_anchor_warning_into_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, policy = self._gated_project_with_bad_provides(root)
            entry_slice = compile_slice(manifest, policy, all_mode=True)
            # count_key（task_id）存在时 warning-history 才落盘；只读调用不写历史。
            report = run_checks(manifest, policy, entry_slice, all_mode=True, task_id="t-anchor-test")
            anchor = [w for w in report.get("warnings", []) if w["kind"] == ANCHOR_WARNING_KIND]
            self.assertEqual(["knowledge.worker"], [w["key"] for w in anchor])
            # 进了 warning-history 体系（只追踪不升级：不在 ESCALATABLE_KINDS 里）。
            history = json.loads((manifest.state_dir / "warning-history.json").read_text(encoding="utf-8"))
            kinds = [entry.get("kind") for entry in (history.get("warnings") or {}).values()]
            self.assertIn(ANCHOR_WARNING_KIND, kinds)

    def test_anchored_card_produces_no_warning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_project(root, gated=True)
            policy_path = root / ".ag2c" / "policy.json"
            raw = json.loads(policy_path.read_text(encoding="utf-8"))
            for card in raw["cards"]:
                if card.get("id") == "knowledge.worker":
                    card["provides"] = ["VALUE 常量"]
            policy_path.write_text(json.dumps(raw), encoding="utf-8")
            manifest = load_manifest(root / ".ag2c" / "manifest.json")
            policy = load_policy(manifest)
            self.assertEqual([], provides_anchor_warnings(manifest, policy))
