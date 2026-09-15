"""9.9 前后台分设（巴林条款）：同任务改产品+考卷的检测、拦截与申报通道。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import bootstrap  # noqa: F401
from support import git_project, write_project

from ag2c.errors import AG2CError
from ag2c.storage import git_private_path
from ag2c.tasks import (
    TASK_SCHEMA,
    _is_product_code,
    _is_verification_asset,
    _task_path,
    declare_front_back,
    front_back_overlap,
)


class ClassificationTests(unittest.TestCase):
    def test_tests_directory_is_verification(self) -> None:
        self.assertTrue(_is_verification_asset("tests/test_foo.py"))
        self.assertTrue(_is_verification_asset("tests/suites.py"))
        self.assertTrue(_is_verification_asset("src/tests/helper.py"))

    def test_test_named_files_are_verification(self) -> None:
        self.assertTrue(_is_verification_asset("src/test_utils.py"))
        self.assertTrue(_is_verification_asset("web/foo_test.py"))
        self.assertTrue(_is_verification_asset("web/foo.test.ts"))

    def test_product_code(self) -> None:
        self.assertTrue(_is_product_code("src/ag2c/checks.py"))
        self.assertTrue(_is_product_code("src/frontend/app.ts"))
        self.assertFalse(_is_product_code("tests/test_foo.py"))
        self.assertFalse(_is_product_code("docs/README.md"))  # 文档不是产品代码
        self.assertFalse(_is_product_code("policy.json"))  # 治理文件另有 governance-changed 通道


class OverlapTests(unittest.TestCase):
    def test_product_only_no_overlap(self) -> None:
        self.assertEqual({"product": [], "verification": []}, front_back_overlap(["src/a.py", "src/b.py"]))

    def test_tests_only_no_overlap(self) -> None:
        self.assertEqual({"product": [], "verification": []}, front_back_overlap(["tests/test_a.py"]))

    def test_docs_plus_tests_no_overlap(self) -> None:
        self.assertEqual({"product": [], "verification": []}, front_back_overlap(["docs/x.md", "tests/test_a.py"]))

    def test_product_plus_tests_is_overlap(self) -> None:
        overlap = front_back_overlap(["src/a.py", "tests/test_a.py"])
        self.assertEqual(["src/a.py"], overlap["product"])
        self.assertEqual(["tests/test_a.py"], overlap["verification"])


def _fake_open_task(root: Path, task_id: str = "t-fake") -> None:
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
        "entry": {"paths": [], "contracts": [], "all": False},
        "worktree": {"path": str(root), "branch": branch},
        "interventions": [],
    }
    path = _task_path(root, task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")


class DeclareTests(unittest.TestCase):
    def test_declare_writes_record_and_intervention(self) -> None:
        with TemporaryDirectory() as tmp:
            root = git_project(Path(tmp) / "proj")
            write_project(root)
            _fake_open_task(root)
            result = declare_front_back(root, reason="产品与测试必须原子交付")
            declaration = result["touches_verification"]
            self.assertTrue(declaration["declared"])
            self.assertEqual("declare", declaration["via"])
            self.assertEqual("产品与测试必须原子交付", declaration["reason"])
            self.assertTrue(declaration["at"])
            record = json.loads(_task_path(root, "t-fake").read_text(encoding="utf-8"))
            self.assertTrue(record["entry"]["touches_verification"]["declared"])
            kinds = [item["kind"] for item in record["interventions"]]
            self.assertIn("front-back-declared", kinds)

    def test_declare_requires_reason(self) -> None:
        with TemporaryDirectory() as tmp:
            root = git_project(Path(tmp) / "proj")
            write_project(root)
            _fake_open_task(root)
            with self.assertRaises(AG2CError):
                declare_front_back(root, reason="  ")

    def test_declare_preserves_start_via(self) -> None:
        with TemporaryDirectory() as tmp:
            root = git_project(Path(tmp) / "proj")
            write_project(root)
            _fake_open_task(root)
            path = _task_path(root, "t-fake")
            record = json.loads(path.read_text(encoding="utf-8"))
            record["entry"]["touches_verification"] = {"declared": True, "reason": "r", "at": "t", "via": "start"}
            path.write_text(json.dumps(record), encoding="utf-8")
            result = declare_front_back(root, reason="补充理由")
            self.assertEqual("start", result["touches_verification"]["via"])

    def test_declare_on_terminal_task_refused(self) -> None:
        with TemporaryDirectory() as tmp:
            root = git_project(Path(tmp) / "proj")
            write_project(root)
            _fake_open_task(root)
            path = _task_path(root, "t-fake")
            record = json.loads(path.read_text(encoding="utf-8"))
            record["state"] = "completed"
            path.write_text(json.dumps(record), encoding="utf-8")
            with self.assertRaises(AG2CError):
                declare_front_back(root, reason="太迟了")


class StartDeclarationTests(unittest.TestCase):
    def _start(self, root: Path, **kwargs):
        from unittest import mock

        from ag2c.task_start import start_task

        portrait = (
            "Done looks like: 服务函数返回值变更。Surfaces: verify 通过。"
            "Out of result: 不动其他模块。验证层: 机器验证 tests 套件全绿，输出片段进 finish proof。无加料。"
        )
        with mock.patch(
            "ag2c.task_start.activation_status",
            return_value={"canonical_root": str(root), "managed": True, "issues": []},
        ):
            return start_task(
                root,
                goal="change",
                path_specs=["app:src/api/service.py"],
                contract_specs=[],
                portrait=portrait,
                worktree_root=root.parent / "worktrees",
                **kwargs,
            )

    def _project(self, tmp: str) -> Path:
        import subprocess

        root = git_project(Path(tmp) / "proj")
        write_project(root)
        subprocess.run(["git", "-C", str(root), "add", "--all"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(root), "commit", "-m", "governance"], check=True, capture_output=True)
        return root

    def test_start_task_records_declaration(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self._project(tmp)
            task = self._start(root, touches_verification=True)
            declaration = task["entry"]["touches_verification"]
            self.assertTrue(declaration["declared"])
            self.assertEqual("start", declaration["via"])

    def test_start_task_default_no_declaration(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self._project(tmp)
            task = self._start(root)
            self.assertNotIn("touches_verification", task["entry"])


class HeadAwarenessTests(unittest.TestCase):
    """检测器只对 diff 新增/修改的函数报警；文件里存量的同名重复不因文件被碰而重提。"""

    def test_preexisting_duplicate_not_reflagged(self) -> None:
        import subprocess
        import tempfile

        from ag2c.checks import _duplicate_warnings
        from ag2c.model import Manifest, Target

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            # 存量重复：old_helper 在两个文件里同名同形，且都已提交
            body = "".join(f"    x{i} = data + {i}\n" for i in range(5))
            (root / "src" / "a.py").write_text(f"def old_helper(data):\n{body}    return x0\n", encoding="utf-8")
            (root / "src" / "b.py").write_text(f"def old_helper(data):\n{body}    return x0\n", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "-C", str(root), "add", "--all"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "base"], check=True, capture_output=True)
            # 本 diff 只动 b.py 里一个无关的新函数
            with (root / "src" / "b.py").open("a", encoding="utf-8") as handle:
                handle.write("\ndef brand_new_unique():\n    return 42\n")
            manifest = Manifest(
                path=root / "manifest.json", project_id="p", project_root=root,
                targets=(Target(target_id="app", path=".", governed_roots=("src",), excludes=()),),
                ledger_path=root / "ledger.jsonl", policy_path=root / "policy.json",
                state_dir=root / "state",
            )
            warnings = _duplicate_warnings(manifest, {"entries": {"paths": [{"path": "src/b.py", "target": "app"}]}})
            self.assertEqual([], warnings)

    def test_newly_added_duplicate_still_flagged(self) -> None:
        import subprocess
        import tempfile

        from ag2c.checks import _duplicate_warnings
        from ag2c.model import Manifest, Target

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            body = "".join(f"    x{i} = data + {i}\n" for i in range(5))
            (root / "src" / "a.py").write_text(f"def helper(data):\n{body}    return x0\n", encoding="utf-8")
            (root / "src" / "b.py").write_text("def unrelated():\n    return 1\n", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "-C", str(root), "add", "--all"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "base"], check=True, capture_output=True)
            # 本 diff 新增一个与 a.py 同名同形的函数——必须报
            with (root / "src" / "b.py").open("a", encoding="utf-8") as handle:
                handle.write(f"\ndef helper(data):\n{body}    return x0\n")
            manifest = Manifest(
                path=root / "manifest.json", project_id="p", project_root=root,
                targets=(Target(target_id="app", path=".", governed_roots=("src",), excludes=()),),
                ledger_path=root / "ledger.jsonl", policy_path=root / "policy.json",
                state_dir=root / "state",
            )
            warnings = _duplicate_warnings(manifest, {"entries": {"paths": [{"path": "src/b.py", "target": "app"}]}})
            self.assertEqual(1, len(warnings))
            self.assertIn("helper", warnings[0]["key"])


class RegulatorBannerTests(unittest.TestCase):
    def test_build_messages_marks_self_grading(self) -> None:
        from ag2c.review import build_messages

        messages = build_messages("画像", "diff", "机器报告", self_grading_declared=True)
        self.assertIn("自我阅卷", messages[1]["content"])
        self.assertIn("巴林条款", messages[1]["content"])

    def test_build_messages_default_no_banner(self) -> None:
        from ag2c.review import build_messages

        messages = build_messages("画像", "diff", "机器报告")
        self.assertNotIn("自我阅卷", messages[1]["content"])
