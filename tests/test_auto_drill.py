"""自动演习节律（finish 后补演超期金丝雀）的测试：建队制、命令正确性、失败不阻断。"""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

import bootstrap  # noqa: F401

from ag2c.config import discover_manifest, load_manifest
from ag2c.ledger import append_event
from ag2c.tasks import _auto_drill

from support import bare_manifest, write_project


def _fake_subprocess(calls: list, returncode: int = 0):
    """替换 tasks 命名空间里的 subprocess 引用（不动全局 subprocess 模块，
    否则 gitops 的 git 调用也会被截获）。"""
    fake = mock.Mock()

    def run(cmd, **kwargs):
        calls.append(list(cmd))
        return SimpleNamespace(returncode=returncode, stdout="", stderr="")

    fake.run = run
    return fake


def _fake_subprocess_with_error():
    fake = mock.Mock()
    fake.run = mock.Mock(side_effect=OSError("no python"))
    return fake


class AutoDrillTests(unittest.TestCase):
    def _project_with_canary(self, root: Path, mode: str = "gate"):
        write_project(root)
        manifest = load_manifest(discover_manifest(root), project_root=root)
        append_event(manifest.ledger_path, "canary", {"mode": mode, "canary": "passed"})
        return root

    def test_no_team_no_drill(self) -> None:
        """建队制：从未手动演习过的项目，超期也不触发（测试夹具天然免疫）。"""
        with TemporaryDirectory() as tmp:
            write_project(Path(tmp))
            calls: list = []
            with mock.patch("ag2c.patrol.DRILL_INTERVAL_DAYS", -1), mock.patch(
                "ag2c.tasks.subprocess", _fake_subprocess(calls)
            ):
                self.assertEqual([], _auto_drill(Path(tmp)))
            self.assertEqual([], calls)

    def test_recent_drill_not_triggered(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self._project_with_canary(Path(tmp))
            calls: list = []
            with mock.patch("ag2c.tasks.subprocess", _fake_subprocess(calls)):
                self.assertEqual([], _auto_drill(root))  # 刚演习过，未超期
            self.assertEqual([], calls)

    def test_overdue_gate_fires_canary_command(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self._project_with_canary(Path(tmp), mode="gate")
            calls: list = []
            with mock.patch("ag2c.patrol.DRILL_INTERVAL_DAYS", -1), mock.patch(
                "ag2c.tasks.subprocess", _fake_subprocess(calls)
            ):
                notes = _auto_drill(root)
            self.assertEqual(1, len(calls))
            self.assertIn("canary", calls[0])
            self.assertIn("咬住了", notes[0])

    def test_drill_command_carries_actor_and_reason(self) -> None:
        """CLI 契约测试：canary 子命令强制 --actor/--reason，缺了就是 exit 2。

        （t21 的教训：mock 掉子进程后命令内容不受测，CLI 契约漂移只能靠
        专门断言命令形状的测试来守。）"""
        with TemporaryDirectory() as tmp:
            root = self._project_with_canary(Path(tmp))
            calls: list = []
            with mock.patch("ag2c.patrol.DRILL_INTERVAL_DAYS", -1), mock.patch(
                "ag2c.tasks.subprocess", _fake_subprocess(calls)
            ):
                _auto_drill(root)
            command = calls[0]
            self.assertIn("--actor", command)
            self.assertIn("ag2c-auto-drill", command)
            self.assertIn("--reason", command)

    def test_overdue_mutation_uses_mutation_mode(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self._project_with_canary(Path(tmp), mode="mutation")
            calls: list = []
            with mock.patch("ag2c.patrol.DRILL_INTERVAL_DAYS", -1), mock.patch(
                "ag2c.tasks.subprocess", _fake_subprocess(calls)
            ):
                _auto_drill(root)
            command = calls[0]
            self.assertIn("canary", command)
            self.assertEqual("mutation", command[command.index("--mode") + 1])

    def test_drill_capture_forces_utf8(self) -> None:
        """Windows 控制台是 GBK：子进程输出含 UTF-8 时 text=True 的默认编码
        会在 reader 线程炸 UnicodeDecodeError（t22 实战教训）；纪要文本也不
        能含 GBK 不可打印字符（finish hints 要打印）。"""
        captured: list = []
        fake = mock.Mock()

        def run(cmd, **kwargs):
            captured.append(kwargs)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        fake.run = run
        with TemporaryDirectory() as tmp:
            root = self._project_with_canary(Path(tmp))
            with mock.patch("ag2c.patrol.DRILL_INTERVAL_DAYS", -1), mock.patch("ag2c.tasks.subprocess", fake):
                notes = _auto_drill(root)
            self.assertEqual("utf-8", captured[0].get("encoding"))
            self.assertEqual("replace", captured[0].get("errors"))
            for note in notes:
                note.encode("gbk")  # GBK 控制台可打印，不抛即过

    def test_failed_drill_notes_alarm_without_raising(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self._project_with_canary(Path(tmp))
            with mock.patch("ag2c.patrol.DRILL_INTERVAL_DAYS", -1), mock.patch(
                "ag2c.tasks.subprocess", _fake_subprocess([], returncode=1)
            ):
                notes = _auto_drill(root)
            self.assertIn("报警", notes[0])

    def test_subprocess_exception_swallowed(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self._project_with_canary(Path(tmp))
            with mock.patch("ag2c.patrol.DRILL_INTERVAL_DAYS", -1), mock.patch(
                "ag2c.tasks.subprocess", _fake_subprocess_with_error()
            ):
                notes = _auto_drill(root)
            self.assertIn("未能执行", notes[0])

    def test_broken_project_returns_empty(self) -> None:
        with TemporaryDirectory() as tmp:
            # 无 manifest 的目录：load/discover 失败 → 静默空纪要
            self.assertEqual([], _auto_drill(Path(tmp)))
            # 账本缺失的 manifest：read_events 失败 → 静默空纪要
            manifest = bare_manifest(Path(tmp) / "ghost")
            self.assertEqual([], _auto_drill(manifest.project_root))


if __name__ == "__main__":
    unittest.main()
