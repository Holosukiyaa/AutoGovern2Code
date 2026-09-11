"""画像修订机制：任务中途按市长指名纠偏更换已锁画像的通道与证据链。

动机：2026-09-10 D→D2 事故——画像锁定口径错了（<=60s 应为 <=90s）却没有
修订通道，只能废弃任务重开。amend_portrait 把修订变成一等公民：lint、
替换、intervention（actor/reason/新旧 digest）落账本，监管可见修订史。
"""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import bootstrap  # noqa: F401
from support import git_project, write_project

from ag2c.config import discover_manifest, load_manifest
from ag2c.errors import AG2CError
from ag2c.ledger import read_events
from ag2c.tasks import TASK_SCHEMA, _task_path, amend_portrait, git_private_path

OLD_PORTRAIT = (
    "Done looks like: 旧承诺——预算口径 60s（机器验证：fast 套件绿）。"
    "Surfaces: 输出 x。Out of result: 不动 y。Inferences: 无加料。"
)
NEW_PORTRAIT = (
    "Done looks like: 新承诺——市长把预算口径从 60s 纠为 90s（机器验证：fast 套件绿）。"
    "Surfaces: 输出 x。Out of result: 不动 y。Inferences: 无加料。"
)


def _fake_open_task(root: Path, task_id: str = "t-amend") -> None:
    """在 git_project 夹具上伪造一个进行中任务记录 + worktree 标记（root 即 worktree）。"""
    import subprocess

    branch = subprocess.run(["git", "-C", str(root), "branch", "--show-current"], check=True, capture_output=True, text=True).stdout.strip()
    marker = git_private_path(root, "ag2c-task.json")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"canonical_root": str(root), "task_id": task_id}), encoding="utf-8")
    record = {
        "schema": TASK_SCHEMA,
        "id": task_id,
        "state": "active",
        "goal": "fake",
        "portrait": OLD_PORTRAIT,
        "entry": {"paths": [], "contracts": [], "all": False},
        "worktree": {"path": str(root), "branch": branch},
        "interventions": [],
    }
    path = _task_path(root, task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")


def _record(root: Path, task_id: str = "t-amend") -> dict:
    return json.loads(_task_path(root, task_id).read_text(encoding="utf-8"))


class AmendPortraitTests(unittest.TestCase):
    def test_amend_replaces_portrait_and_records_intervention(self) -> None:
        with TemporaryDirectory() as tmp:
            root = git_project(Path(tmp) / "proj")
            write_project(root)
            _fake_open_task(root)
            result = amend_portrait(root, portrait=NEW_PORTRAIT, actor="holo", reason="预算口径纠偏：60s→90s")
            amended = result["portrait_amended"]
            self.assertEqual("t-amend", result["task"])
            self.assertEqual("holo", amended["actor"])
            self.assertEqual("预算口径纠偏：60s→90s", amended["reason"])
            self.assertEqual(hashlib.sha256(OLD_PORTRAIT.encode("utf-8")).hexdigest(), amended["old_digest"])
            self.assertEqual(hashlib.sha256(NEW_PORTRAIT.encode("utf-8")).hexdigest(), amended["new_digest"])
            record = _record(root)
            self.assertEqual(NEW_PORTRAIT, record["portrait"])
            intervention = next(item for item in record["interventions"] if item["kind"] == "portrait-amended")
            self.assertEqual("holo", intervention["actor"])
            self.assertEqual(amended["old_digest"], intervention["old_digest"])
            self.assertEqual(amended["new_digest"], intervention["new_digest"])
            self.assertTrue(intervention["occurred_at"])
            self.assertTrue(intervention["ledger_event_digest"])

    def test_amend_intervention_lands_in_ledger(self) -> None:
        with TemporaryDirectory() as tmp:
            root = git_project(Path(tmp) / "proj")
            write_project(root)
            _fake_open_task(root)
            amend_portrait(root, portrait=NEW_PORTRAIT, actor="holo", reason="预算口径纠偏：60s→90s")
            manifest = load_manifest(discover_manifest(root))
            events = [
                event
                for event in read_events(manifest.ledger_path)
                if event.get("event_type") == "governance-intervention"
                and event.get("payload", {}).get("kind") == "portrait-amended"
            ]
            self.assertEqual(1, len(events))
            payload = events[0]["payload"]
            self.assertEqual("t-amend", payload["task_id"])
            self.assertEqual("holo", payload["actor"])
            self.assertEqual("预算口径纠偏：60s→90s", payload["reason"])

    def test_amend_lint_failure_keeps_old_portrait(self) -> None:
        with TemporaryDirectory() as tmp:
            root = git_project(Path(tmp) / "proj")
            write_project(root)
            _fake_open_task(root)
            vague = "Done looks like: 优化一下让它正常工作。Surfaces: 看不出差别。"
            with self.assertRaises(AG2CError):
                amend_portrait(root, portrait=vague, actor="holo", reason="试图放宽")
            record = _record(root)
            self.assertEqual(OLD_PORTRAIT, record["portrait"])
            self.assertEqual([], record["interventions"])

    def test_amend_requires_actor_and_reason(self) -> None:
        with TemporaryDirectory() as tmp:
            root = git_project(Path(tmp) / "proj")
            write_project(root)
            _fake_open_task(root)
            with self.assertRaises(AG2CError):
                amend_portrait(root, portrait=NEW_PORTRAIT, actor="  ", reason="预算口径纠偏")
            with self.assertRaises(AG2CError):
                amend_portrait(root, portrait=NEW_PORTRAIT, actor="holo", reason=" ")
            self.assertEqual(OLD_PORTRAIT, _record(root)["portrait"])

    def test_amend_identical_portrait_refused(self) -> None:
        with TemporaryDirectory() as tmp:
            root = git_project(Path(tmp) / "proj")
            write_project(root)
            _fake_open_task(root)
            with self.assertRaises(AG2CError):
                amend_portrait(root, portrait=OLD_PORTRAIT, actor="holo", reason="无变化")
            self.assertEqual([], _record(root)["interventions"])

    def test_amend_on_terminal_task_refused(self) -> None:
        with TemporaryDirectory() as tmp:
            root = git_project(Path(tmp) / "proj")
            write_project(root)
            _fake_open_task(root)
            path = _task_path(root, "t-amend")
            record = json.loads(path.read_text(encoding="utf-8"))
            record["state"] = "completed"
            path.write_text(json.dumps(record), encoding="utf-8")
            with self.assertRaises(AG2CError):
                amend_portrait(root, portrait=NEW_PORTRAIT, actor="holo", reason="太迟了")


class EntryPointTests(unittest.TestCase):
    """画像承诺③的机器验证：CLI 分发与 MCP 处理器两个入口都要真走一遍。"""

    def test_cli_dispatch_prints_result_json(self) -> None:
        import io
        import os
        from contextlib import redirect_stdout

        from ag2c.cli import main

        with TemporaryDirectory() as tmp:
            root = git_project(Path(tmp) / "proj")
            write_project(root)
            _fake_open_task(root)
            previous = os.getcwd()
            output = io.StringIO()
            try:
                os.chdir(root)
                with redirect_stdout(output):
                    exit_code = main(
                        ["task", "amend-portrait", "--portrait", NEW_PORTRAIT, "--actor", "holo", "--reason", "预算口径纠偏：60s→90s"]
                    )
            finally:
                os.chdir(previous)
            self.assertEqual(0, exit_code)
            payload = json.loads(output.getvalue())
            self.assertEqual("t-amend", payload["task"])
            self.assertEqual(
                hashlib.sha256(OLD_PORTRAIT.encode("utf-8")).hexdigest(),
                payload["portrait_amended"]["old_digest"],
            )
            self.assertEqual(NEW_PORTRAIT, _record(root)["portrait"])

    def test_cli_requires_actor(self) -> None:
        import io
        from contextlib import redirect_stderr

        from ag2c.cli import main

        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                main(["task", "amend-portrait", "--portrait", "x", "--reason", "r"])

    def test_cli_portrait_file_branch(self) -> None:
        import io
        import os
        from contextlib import redirect_stdout

        from ag2c.cli import main

        with TemporaryDirectory() as tmp:
            root = git_project(Path(tmp) / "proj")
            write_project(root)
            _fake_open_task(root)
            portrait_file = Path(tmp) / "new_portrait.md"
            portrait_file.write_text(NEW_PORTRAIT + "\n", encoding="utf-8")  # 文件原样读入，带尾换行
            previous = os.getcwd()
            output = io.StringIO()
            try:
                os.chdir(root)
                with redirect_stdout(output):
                    exit_code = main(
                        ["task", "amend-portrait", "--portrait-file", str(portrait_file), "--actor", "holo", "--reason", "预算口径纠偏：60s→90s"]
                    )
            finally:
                os.chdir(previous)
            self.assertEqual(0, exit_code)
            payload = json.loads(output.getvalue())
            self.assertEqual("t-amend", payload["task"])
            self.assertEqual(NEW_PORTRAIT, _record(root)["portrait"])

    def test_cli_portrait_file_same_content_refused(self) -> None:
        """同文画像经 --portrait-file 提交（带首尾空白）也必须判相同——拒绝且不记干预。"""
        import io
        import os
        from contextlib import redirect_stderr

        from ag2c.cli import main

        with TemporaryDirectory() as tmp:
            root = git_project(Path(tmp) / "proj")
            write_project(root)
            _fake_open_task(root)
            portrait_file = Path(tmp) / "same_portrait.md"
            portrait_file.write_text("\n" + OLD_PORTRAIT + "\n\n", encoding="utf-8")
            previous = os.getcwd()
            try:
                os.chdir(root)
                with redirect_stderr(io.StringIO()):
                    exit_code = main(
                        ["task", "amend-portrait", "--portrait-file", str(portrait_file), "--actor", "holo", "--reason", "无变化"]
                    )
            finally:
                os.chdir(previous)
            self.assertEqual(2, exit_code)  # AG2CError → 非零退出
            record = _record(root)
            self.assertEqual(OLD_PORTRAIT, record["portrait"])
            self.assertEqual([], record["interventions"])

    def test_cli_portrait_file_missing_is_ag2c_error(self) -> None:
        import io
        import os
        from contextlib import redirect_stderr

        from ag2c.cli import main

        with TemporaryDirectory() as tmp:
            root = git_project(Path(tmp) / "proj")
            write_project(root)
            _fake_open_task(root)
            previous = os.getcwd()
            try:
                os.chdir(root)
                with redirect_stderr(io.StringIO()):
                    exit_code = main(
                        ["task", "amend-portrait", "--portrait-file", str(Path(tmp) / "nope.md"), "--actor", "holo", "--reason", "r"]
                    )
            finally:
                os.chdir(previous)
            self.assertEqual(2, exit_code)

    def test_mcp_handler_roundtrip_and_schema(self) -> None:
        from ag2c.mcp_server import HANDLERS, _call_task_amend_portrait, tool_defs

        schema = next(item for item in tool_defs() if item["name"] == "ag2c_task_amend_portrait")
        self.assertEqual(["portrait", "actor", "reason"], schema["inputSchema"]["required"])
        self.assertIs(HANDLERS["ag2c_task_amend_portrait"], _call_task_amend_portrait)
        with TemporaryDirectory() as tmp:
            root = git_project(Path(tmp) / "proj")
            write_project(root)
            _fake_open_task(root)
            result = _call_task_amend_portrait(
                {"cwd": str(root), "portrait": NEW_PORTRAIT, "actor": "holo", "reason": "预算口径纠偏：60s→90s"}
            )
            self.assertEqual("t-amend", result["task"])
            # 返回体与账本条目一致
            manifest = load_manifest(discover_manifest(root))
            events = [
                event
                for event in read_events(manifest.ledger_path)
                if event.get("event_type") == "governance-intervention"
                and event.get("payload", {}).get("kind") == "portrait-amended"
            ]
            self.assertEqual(1, len(events))
            payload = events[0]["payload"]
            self.assertEqual(result["portrait_amended"]["new_digest"], payload["new_digest"])
            self.assertEqual("holo", payload["actor"])


if __name__ == "__main__":
    unittest.main()
