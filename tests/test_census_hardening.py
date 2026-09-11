from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bootstrap

from support import write_project


def _git_fixture(root: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--no-verify", "-m", "base"],
        cwd=root,
        check=True,
        capture_output=True,
    )


class CensusCacheKeyRootTests(unittest.TestCase):
    """检出根路径必须进普查缓存 key。

    canonical 与任务 worktree 共享同一份 policy/state 文件（外部存储），
    HEAD 与 dirty 状态相同的瞬间（任务刚开工、未提交）缺了 root 就会碰撞。
    内容相同时碰撞无害，但「碰撞即同内容」应是设计而非运气。
    """

    def test_checkout_root_is_part_of_the_key(self) -> None:
        from ag2c.households import _census_cache_key

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, policy = write_project(root)
            # 固定 git 侧输入（HEAD/dirty 相同），只让检出根路径不同——
            # 复现 canonical/worktree 共享 policy+state 且内容一致的瞬间。
            with patch("ag2c.households._git", return_value=""):
                key_canonical = _census_cache_key(manifest, policy)
                sibling = root / "sibling-worktree"
                with patch.object(type(manifest), "target_root", return_value=sibling):
                    key_worktree = _census_cache_key(manifest, policy)
            self.assertIsNotNone(key_canonical)
            self.assertIsNotNone(key_worktree)
            self.assertNotEqual(key_canonical, key_worktree)


class CensusCodeVersionTests(unittest.TestCase):
    """每条普查记录带代码版本戳：digest 语义随代码演进，长驻进程
    （MCP server/托盘）可能跑旧代码，版本戳让「哪个年代的工具录的」可查。"""

    def test_record_carries_code_version(self) -> None:
        import ag2c
        from ag2c.household_commands import review_census
        from ag2c.households import census_path

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _policy = write_project(root)
            _git_fixture(root)
            review_census(root, card_ids=[], all_cards=True, actor="test", reason="version stamp")
            state = json.loads(census_path(manifest).read_text(encoding="utf-8"))
            self.assertTrue(state["records"])
            for record in state["records"]:
                self.assertEqual(ag2c.__version__, record["code_version"])


class McpCanonicalCensusWarningTests(unittest.TestCase):
    """cwd 脚枪提示：在 canonical 检出上录普查且有开放任务时，结果带 warning。

    finish 的新鲜度门禁读的是 worktree 的普查记录；在 canonical 上录的记录
    对进行中的任务不算数。警告不阻塞——canonical 普查本身合法（如发版后全量）。
    """

    def _record(self, root: Path) -> dict:
        from ag2c.mcp_server import _call_census

        return _call_census({"record": True, "all": True, "actor": "test", "reason": "probe", "cwd": str(root)})

    def test_warns_on_canonical_with_open_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_project(root)
            _git_fixture(root)
            open_tasks = [
                {"id": "20260911-000000-x", "state": "open", "worktree": {"path": "C:/wt/x"}},
                {"id": "20260910-000000-done", "state": "completed", "worktree": {"path": "C:/wt/done"}},
            ]
            with (
                patch("ag2c.enrollment.activation_status", return_value={"canonical_root": str(root)}),
                patch("ag2c.tasks.list_tasks", return_value=open_tasks),
            ):
                result = self._record(root)
            warning = result.get("warning", "")
            self.assertIn("20260911-000000-x", warning)
            self.assertIn("C:/wt/x", warning)
            # 终态任务不点名
            self.assertNotIn("20260910-000000-done", warning)

    def test_no_warning_from_worktree_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_project(root)
            _git_fixture(root)
            open_tasks = [{"id": "20260911-000000-x", "state": "open", "worktree": {"path": str(root)}}]
            with (
                patch(
                    "ag2c.enrollment.activation_status",
                    return_value={"canonical_root": str(root / "canonical-elsewhere")},
                ),
                patch("ag2c.tasks.list_tasks", return_value=open_tasks),
            ):
                result = self._record(root)
            self.assertNotIn("warning", result)

    def test_no_warning_when_no_open_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_project(root)
            _git_fixture(root)
            with (
                patch("ag2c.enrollment.activation_status", return_value={"canonical_root": str(root)}),
                patch("ag2c.tasks.list_tasks", return_value=[]),
            ):
                result = self._record(root)
            self.assertNotIn("warning", result)


if __name__ == "__main__":
    unittest.main()
