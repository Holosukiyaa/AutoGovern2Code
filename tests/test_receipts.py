from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import bootstrap  # noqa: F401
from support import git_project

from ag2c.config import discover_manifest, load_manifest, load_policy
from ag2c.enrollment import enroll_project
from ag2c.errors import AG2CError
from ag2c.gitops import commit_line_deltas, git, head, line_deltas
from ag2c.receipts import (
    EVIDENCE_TRAILER,
    TASK_TRAILER,
    build_receipt,
    verify_commit_receipt,
    write_receipt,
)
from ag2c.util import digest_json


def _commit_all(root: Path, message: str) -> str:
    git(root, "add", "-A")
    # Enrolled fixtures carry the AG2C guard hook; tests commit fixture state
    # directly, so skip hooks explicitly.
    git(root, "commit", "--no-verify", "-qm", message, check=True)
    return head(root)


def _fake_task(root: Path, base: str, branch: str, verification: dict) -> dict:
    return {
        "id": "20260908-000000-receipt-line-deltas-test-0000",
        "goal": "test receipt line deltas",
        "delivery": {"request": "q", "outcome": "a", "kind": "change"},
        "source": {"head": base, "branch": branch},
        "entry": {"paths": [], "contracts": [], "all": False},
        "worktree": {"path": str(root), "branch": branch},
        "verifications": [verification],
        "interventions": [],
        "start_ledger_event_digest": "0" * 64,
    }


def _verification() -> dict:
    return {
        "passed": True,
        "changed_paths": [],
        "change_digest": "0" * 64,
        "route_state": "precise",
        "route": {"fallback_reasons": [], "fallback_targets": []},
        "route_cards": [],
        "slice_digest": "0" * 64,
        "checker_results": [{"id": "check.fake", "stage": "floor", "status": "passed", "exit_code": 0}],
        "acceptance": {},
        "occurred_at": "2026-09-08T00:00:00+00:00",
        "check_ledger_event_digest": "0" * 64,
        "ledger_event_digest": "0" * 64,
    }


def _verification_for(root: Path, base: str) -> dict:
    """A verification payload matching the current working tree, like verify_task's."""
    from ag2c.gitops import change_digest, changed_paths

    verification = _verification()
    verification["changed_paths"] = changed_paths(root, base)
    verification["change_digest"] = change_digest(root, base)
    return verification


class LineDeltaTests(unittest.TestCase):
    def test_numstat_matches_edit_sizes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = git_project(Path(directory) / "repo")
            base = head(root)
            (root / "src" / "value.py").write_text("VALUE = 1\nEXTRA = 2\nMORE = 3\n", encoding="utf-8")
            (root / "notes.txt").write_text("hello\n", encoding="utf-8")
            tip = _commit_all(root, "change")
            rows = {row["path"]: row for row in commit_line_deltas(root, base, tip)}
            self.assertEqual({"path": "notes.txt", "added": 1, "removed": 0}, rows["notes.txt"])
            self.assertEqual(2, rows["src/value.py"]["added"])
            self.assertEqual(0, rows["src/value.py"]["removed"])

    def test_binary_file_records_none_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = git_project(Path(directory) / "repo")
            base = head(root)
            (root / "blob.bin").write_bytes(b"\x00\x01\x02\xff")
            tip = _commit_all(root, "binary")
            rows = commit_line_deltas(root, base, tip)
            self.assertEqual([{"path": "blob.bin", "added": None, "removed": None}], rows)

    def test_exclude_prefixes_drop_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = git_project(Path(directory) / "repo")
            base = head(root)
            (root / "keep.txt").write_text("k\n", encoding="utf-8")
            dropped = root / "vendor"
            dropped.mkdir()
            (dropped / "skip.txt").write_text("s\n", encoding="utf-8")
            tip = _commit_all(root, "change")
            rows = commit_line_deltas(root, base, tip, exclude_prefixes=("vendor",))
            self.assertEqual(["keep.txt"], [row["path"] for row in rows])

    def test_worktree_deltas_cover_untracked_and_uncommitted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = git_project(Path(directory) / "repo")
            base = head(root)
            (root / "src" / "value.py").write_text("VALUE = 1\nEXTRA = 2\n", encoding="utf-8")
            (root / "fresh.txt").write_text("a\nb\n", encoding="utf-8")
            (root / "raw.bin").write_bytes(b"\x00\x01\x02")
            rows = {row["path"]: row for row in line_deltas(root, base)}
            self.assertEqual(1, rows["src/value.py"]["added"])
            self.assertEqual({"path": "fresh.txt", "added": 2, "removed": 0}, rows["fresh.txt"])
            self.assertEqual({"path": "raw.bin", "added": None, "removed": None}, rows["raw.bin"])
            # Once committed verbatim, the commit-side recompute agrees.
            tip = _commit_all(root, "change")
            self.assertEqual(line_deltas(root, base), commit_line_deltas(root, base, tip))


class ReceiptDeltaTests(unittest.TestCase):
    def _enrolled(self, directory: str) -> tuple[Path, object, object, str]:
        root = git_project(Path(directory) / "repo")
        # skill_root 必须隔离：缺省会装进操作者真实的 ~/.codex/skills，
        # 既污染环境又在目录被占用时炸 PermissionError。
        enroll_project(root, skill_root=Path(directory) / "skills", harnesses=("agents",))
        manifest = load_manifest(discover_manifest(root), project_root=root)
        policy = load_policy(manifest)
        base = head(root)
        return root, manifest, policy, base

    def test_build_receipt_records_line_deltas_before_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, manifest, policy, base = self._enrolled(directory)
            # The verified change is still uncommitted at receipt time.
            (root / "src" / "value.py").write_text("VALUE = 1\nEXTRA = 2\n", encoding="utf-8")
            (root / "fresh.txt").write_text("new\n", encoding="utf-8")
            task = _fake_task(root, base, "ag2c/test-branch", _verification())
            receipt = build_receipt(manifest, policy, task)
            rows = {row["path"]: row for row in receipt["line_deltas"]}
            self.assertEqual(1, rows["src/value.py"]["added"])
            self.assertEqual({"path": "fresh.txt", "added": 1, "removed": 0}, rows["fresh.txt"])

    def test_write_receipt_twice_overwrites_without_raising(self) -> None:
        """重试验收会重写同 task_id 的回执：目录已存在也不能崩。 变异记录：write_receipt 的 mkdir exist_ok True→False 曾存活 （t21 自动演习抓获，看板常驻警情）。"""
        with tempfile.TemporaryDirectory() as directory:
            root, manifest, policy, base = self._enrolled(directory)
            task = _fake_task(root, base, "ag2c/test-branch", _verification_for(root, base))
            receipt = build_receipt(manifest, policy, task)
            first = write_receipt(manifest, receipt)
            second = write_receipt(manifest, receipt)  # 目录已存在，必须幂等覆盖
            self.assertEqual(first, second)
            self.assertTrue(second.exists())

    def test_write_receipt_serialization_is_sorted_utf8_and_atomic(self) -> None:
        """回执落盘格式是证据链的一部分：键序字典序、非 ASCII 原文、无临时文件残留。 变异记录：write_receipt 的 json.dumps 布尔参数（ensure_ascii=False、 sort_keys=True）翻转曾存活（危房名单 2026-09-09 变异存活警情）。"""
        with tempfile.TemporaryDirectory() as directory:
            root, manifest, policy, base = self._enrolled(directory)
            task = _fake_task(root, base, "ag2c/test-branch", _verification_for(root, base))
            receipt = build_receipt(manifest, policy, task)
            receipt["delivery"] = {"goal": "修复中文乱码", "outcome": "回执含中文原文"}
            path = write_receipt(manifest, receipt)
            raw = path.read_text(encoding="utf-8")
            # ensure_ascii=False：中文以 UTF-8 原文落盘，不是 \uXXXX 转义
            self.assertIn("修复中文乱码", raw)
            self.assertNotIn("\\u4fee", raw)
            # sort_keys=True：顶层键按字典序落盘
            keys = list(json.loads(raw).keys())
            self.assertEqual(sorted(keys), keys)
            # os.replace 生效：不留 .tmp 临时文件残留
            self.assertFalse(path.with_suffix(path.suffix + ".tmp").exists())

    def test_ci_accepts_matching_deltas(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, manifest, policy, base = self._enrolled(directory)
            (root / "src" / "value.py").write_text("VALUE = 1\nEXTRA = 2\n", encoding="utf-8")
            task = _fake_task(root, base, "ag2c/test-branch", _verification_for(root, base))
            receipt = build_receipt(manifest, policy, task)
            write_receipt(manifest, receipt)
            message = f"change\n\n{TASK_TRAILER}: {task['id']}\n{EVIDENCE_TRAILER}: {receipt['receipt_digest']}"
            _commit_all(root, message)
            verify_commit_receipt(root, "HEAD")  # must not raise

    def test_ci_rejects_tampered_deltas(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, manifest, policy, base = self._enrolled(directory)
            (root / "src" / "value.py").write_text("VALUE = 1\nEXTRA = 2\n", encoding="utf-8")
            task = _fake_task(root, base, "ag2c/test-branch", _verification_for(root, base))
            receipt = build_receipt(manifest, policy, task)
            # Tamper: inflate the added count, then re-seal the receipt so the
            # digest trailer matches and only the line-delta recompute can catch it.
            receipt["line_deltas"][0]["added"] += 100
            receipt.pop("receipt_digest", None)
            receipt["receipt_digest"] = digest_json(receipt)
            write_receipt(manifest, receipt)
            message = f"change\n\n{TASK_TRAILER}: {task['id']}\n{EVIDENCE_TRAILER}: {receipt['receipt_digest']}"
            _commit_all(root, message)
            with self.assertRaises(AG2CError) as raised:
                verify_commit_receipt(root, "HEAD")
            self.assertIn("line deltas", str(raised.exception))

    def test_ci_tolerates_receipts_without_deltas(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, manifest, policy, base = self._enrolled(directory)
            (root / "src" / "value.py").write_text("VALUE = 1\nEXTRA = 2\n", encoding="utf-8")
            task = _fake_task(root, base, "ag2c/test-branch", _verification_for(root, base))
            receipt = build_receipt(manifest, policy, task)
            # Simulate a pre-line_deltas receipt.
            receipt.pop("line_deltas", None)
            receipt.pop("receipt_digest", None)
            receipt["receipt_digest"] = digest_json(receipt)
            write_receipt(manifest, receipt)
            message = f"change\n\n{TASK_TRAILER}: {task['id']}\n{EVIDENCE_TRAILER}: {receipt['receipt_digest']}"
            _commit_all(root, message)
            verify_commit_receipt(root, "HEAD")  # must not raise
