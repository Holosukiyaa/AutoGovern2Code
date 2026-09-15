"""正主分支守卫：start/finish 前置检查正主处于登记主干。 2026-09-09 事故：正主检出停在旧 feature 分支上，全天 12 个任务的合并 全部落在它头上，主干原地不动而无人报警——finish 只检查"分支变没变"， 从不检查"是不是主干"。本模块测试身份检查（require_trunk）、start 集成 拦截与 govern trunk 登记命令。"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import bootstrap  # noqa: F401

from ag2c.errors import AG2CError
from ag2c.govern import configure_trunk
from ag2c.tasks import require_trunk, start_task

from support import _git, git_project, write_project


def _project(root: Path) -> Path:
    root = git_project(root)
    write_project(root)
    _git(root, "add", "--all")
    _git(root, "commit", "-m", "governance")
    return root


def _register_trunk(root: Path, branch: str = "main") -> None:
    manifest_path = root / ".ag2c" / "manifest.json"
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw["project"]["trunk"] = branch
    manifest_path.write_text(json.dumps(raw), encoding="utf-8")
    _git(root, "add", "--all")
    _git(root, "commit", "-m", "register trunk")


def _load_manifest(root: Path):
    from ag2c.config import discover_manifest, load_manifest

    return load_manifest(discover_manifest(root), project_root=root)


class RequireTrunkTests(unittest.TestCase):
    def test_unregistered_trunk_refused_with_guidance(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _project(Path(tmp) / "proj")
            # 模拟未登记的老项目：去掉夹具自带的 trunk（write_project 已与生产保真，自带 trunk）
            manifest_path = root / ".ag2c" / "manifest.json"
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            del raw["project"]["trunk"]
            manifest_path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(AG2CError) as ctx:
                require_trunk(_load_manifest(root), root)
            self.assertIn("govern trunk", str(ctx.exception))

    def test_wrong_branch_refused_naming_both(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _project(Path(tmp) / "proj")
            _register_trunk(root)
            _git(root, "checkout", "-b", "feature/old")
            with self.assertRaises(AG2CError) as ctx:
                require_trunk(_load_manifest(root), root)
            message = str(ctx.exception)
            self.assertIn("feature/old", message)
            self.assertIn("main", message)

    def test_on_trunk_returns_branch(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _project(Path(tmp) / "proj")
            _register_trunk(root)
            self.assertEqual("main", require_trunk(_load_manifest(root), root))


class StartTaskGuardTests(unittest.TestCase):
    def _start(self, root: Path):
        portrait = (
            "Done looks like: 服务函数返回值变更。Surfaces: verify 通过。"
            "Out of result: 不动其他模块。验证层: 机器验证 tests 套件全绿，输出片段进 finish proof。无加料。"
        )
        with mock.patch(
            "ag2c.tasks.activation_status",
            return_value={"canonical_root": str(root), "managed": True, "issues": []},
        ):
            return start_task(
                root,
                goal="change",
                path_specs=["app:src/api/service.py"],
                contract_specs=[],
                portrait=portrait,
                worktree_root=root.parent / "worktrees",
            )

    def test_start_refused_off_trunk(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _project(Path(tmp) / "proj")
            _register_trunk(root)
            _git(root, "checkout", "-b", "feature/old")
            with self.assertRaises(AG2CError) as ctx:
                self._start(root)
            self.assertIn("登记主干", str(ctx.exception))

    def test_start_allowed_on_trunk(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _project(Path(tmp) / "proj")
            _register_trunk(root)
            task = self._start(root)
            self.assertEqual("main", task["source"]["branch"])


class ConfigureTrunkTests(unittest.TestCase):
    def test_register_writes_manifest_and_ledger(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _project(Path(tmp) / "proj")
            # 夹具自带 trunk=main（与生产保真）；登记一个真实存在的新分支，走变更路径
            _git(root, "branch", "develop")
            result = configure_trunk(root, branch="develop", actor="test", reason="变更主干")
            self.assertEqual({"from": "main", "to": "develop"}, result["changes"]["trunk"])
            self.assertEqual("develop", _load_manifest(root).trunk)
            events = [
                json.loads(line)
                for line in (root / ".ag2c" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            trunk_events = [
                e for e in events
                if e.get("event_type") == "governance-applied" and e["payload"].get("kind") == "trunk"
            ]
            self.assertEqual(1, len(trunk_events))

    def test_nonexistent_branch_refused(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _project(Path(tmp) / "proj")
            with self.assertRaises(AG2CError):
                configure_trunk(root, branch="nope", actor="test", reason="不存在的分支")

    def test_same_branch_is_noop(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _project(Path(tmp) / "proj")
            _register_trunk(root)
            result = configure_trunk(root, branch="main", actor="test", reason="重复登记")
            self.assertEqual({}, result["changes"])


class TrunkCliTests(unittest.TestCase):
    """CLI 层全路径：解析 → 分发 → 输出。t18 只测了函数层，接线缺 --format 导致合并后首次真实调用崩溃——每一层都要有自己的测试。"""

    def test_govern_trunk_cli_end_to_end(self) -> None:
        import io
        import os

        from ag2c.cli_main import main

        with TemporaryDirectory() as tmp:
            root = _project(Path(tmp) / "proj")
            _git(root, "branch", "develop")
            previous = Path.cwd()
            stdout = io.StringIO()
            try:
                os.chdir(root)
                with mock.patch("sys.stdout", stdout):
                    exit_code = main(["govern", "trunk", "--branch", "develop", "--actor", "test", "--reason", "CLI 全路径"])
            finally:
                os.chdir(previous)
            self.assertEqual(0, exit_code)
            payload = json.loads(stdout.getvalue())
            self.assertEqual("trunk", payload["kind"])
            self.assertEqual({"from": "main", "to": "develop"}, payload["changes"]["trunk"])
            self.assertEqual("develop", _load_manifest(root).trunk)
