"""文件粒度户口（grain=file，t59）：删除门的单文件通道。

删除门（tasks._assert_retirement_diff）此前只认目录户口：根文件拿不到
jurisdiction（directory_scope 只要 dir/**），活跃房间内的单文件删除被
cannot-delete-active-household / retirement-diff-touches-active 挡死——
t54 的两个 imgui.ini 因此只能冻结。文件粒度户口是最小补救：精确文件路径
登记、可退役、可确认，已退役文件户口遮蔽房间户口（具体者优先）。

夹具预算：setUpClass 共享一个 git 仓库，每个测试用独立文件名/卡 id，
删除后即时 commit 保持工作区干净（git diff <head> 只看本测试的删除）。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import bootstrap  # noqa: F401

from ag2c.errors import AG2CError, ConfigurationError
from ag2c.households import census_report, file_scope, households_covering_path
from ag2c.household_commands import confirm_retirement, register_household, retire_household
from ag2c.tasks import _assert_retirement_diff
from support import _git, git_project, write_project


class FileScopeTests(unittest.TestCase):
    """纯函数校验：文件户口的 scope 必须是精确文件路径。"""

    def test_exact_file_path_accepted(self):
        self.assertEqual(file_scope("imgui.ini"), "imgui.ini")
        self.assertEqual(file_scope("tests/imgui.ini"), "tests/imgui.ini")

    def test_glob_rejected(self):
        for pattern in ("*.ini", "tests/?.ini", "tests/[ab].ini"):
            with self.subTest(pattern=pattern):
                with self.assertRaises(ConfigurationError):
                    file_scope(pattern)

    def test_directory_glob_rejected(self):
        with self.assertRaises(ConfigurationError):
            file_scope("tests/**")
        with self.assertRaises(ConfigurationError):
            file_scope("**")

    def test_dotdot_rejected(self):
        with self.assertRaises(ConfigurationError):
            file_scope("../outside.ini")


class FileHouseholdGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        cls.root = git_project(Path(cls._tmp.name) / "demo")
        write_project(cls.root)

    def _commit_file(self, name: str, content: str = "x\n") -> str:
        """写入并提交文件，返回含该文件的 head（删除门 diff 的基准）。"""
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        _git(self.root, "add", name)
        _git(self.root, "commit", "-m", f"track {name}")
        return _git(self.root, "rev-parse", "HEAD")

    def _delete_and_commit(self, name: str) -> None:
        """删除后立即 commit：保持工作区干净，下个测试的 diff 不受污染。"""
        (self.root / name).unlink()
        _git(self.root, "add", "--all")
        _git(self.root, "commit", "-m", f"delete {name}")

    def _gate(self, head: str, changed: list[str]) -> None:
        task = {"id": "t-file-grain-test", "source": {"head": head}}
        _assert_retirement_diff(self.root, self.root, task, changed)

    def _register_file_household(self, card_id: str, path: str, *, decider: str = "") -> None:
        register_household(
            self.root,
            card_id=card_id,
            title=card_id,
            summary=f"file household for {path}",
            includes=[path],
            excludes=[],
            floors=["floor.api"],
            capability=path,
            implementation=f"file.{card_id}",
            status="current",
            grain="file",
            decider=decider,
            actor="test",
            reason="file-grain gate test",
        )

    def test_file_household_covers_exact_path_only(self):
        head = self._commit_file("t59-cover.ini")
        self._register_file_household("knowledge.t59-cover", "t59-cover.ini")
        from ag2c.config import discover_manifest, load_manifest, load_policy

        manifest = load_manifest(discover_manifest(self.root), project_root=self.root)
        report = census_report(manifest, load_policy(manifest))
        covering = {h["id"] for h in households_covering_path(report, "app", "t59-cover.ini")}
        self.assertIn("knowledge.t59-cover", covering)
        not_covered = {h["id"] for h in households_covering_path(report, "app", "t59-other.ini")}
        self.assertNotIn("knowledge.t59-cover", not_covered)

    def test_file_household_rejects_glob_include(self):
        with self.assertRaises((AG2CError, ConfigurationError)):
            self._register_file_household("knowledge.t59-glob", "*.ini")

    def test_retired_file_household_allows_deletion_in_active_room(self):
        """退役+确认的文件户口放行删除，即使所在房间（floor.api）仍 active。"""
        head = self._commit_file("src/api/t59-legacy.ini")
        self._register_file_household("knowledge.t59-legacy", "src/api/t59-legacy.ini", decider="confirm")
        retire_household(self.root, card_id="knowledge.t59-legacy", actor="test", reason="retire for deletion")
        with self.assertRaisesRegex(AG2CError, "retirement-confirm-required"):
            (self.root / "src/api/t59-legacy.ini").unlink()
            try:
                self._gate(head, ["src/api/t59-legacy.ini"])
            finally:
                _git(self.root, "checkout", "--", "src/api/t59-legacy.ini")
        confirm_retirement(self.root, card_id="knowledge.t59-legacy", actor="test", reason="human fuse")
        (self.root / "src/api/t59-legacy.ini").unlink()
        try:
            self._gate(head, ["src/api/t59-legacy.ini"])  # 不抛异常即放行
        finally:
            _git(self.root, "add", "--all")
            _git(self.root, "commit", "-m", "delete src/api/t59-legacy.ini")

    def test_floor_only_file_delete_is_unowned(self):
        """floor 不算删除门的 owner（households_covering_path 只看 jurisdiction）：
        仅被 floor 覆盖的文件删除报 cannot-delete-unowned——钉死这个真实语义。
        手改 policy 加隔离楼层 floor.t59iso，避开共享夹具里其他测试累积的
        knowledge 户口（如 src/api/** 的 t59-cur）污染。"""
        policy_path = self.root / ".ag2c" / "policy.json"
        raw = json.loads(policy_path.read_text(encoding="utf-8"))
        raw["cards"].append(
            {
                "id": "floor.t59iso",
                "type": "floor",
                "title": "t59 isolated floor",
                "summary": "Isolated floor for floor-only deletion pin.",
                "scopes": [{"target": "app", "include": ["src/t59iso/**"], "ownership": "primary"}],
                "checkers": ["check.floor"],
            }
        )
        policy_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        head = self._commit_file("src/t59iso/t59-active.ini")
        (self.root / "src/t59iso/t59-active.ini").unlink()
        try:
            with self.assertRaisesRegex(AG2CError, "^cannot-delete-unowned"):
                self._gate(head, ["src/t59iso/t59-active.ini"])
        finally:
            _git(self.root, "checkout", "--", "src/t59iso/t59-active.ini")

    def test_changed_path_touching_active_household_blocked(self):
        """retirement-diff-touches-active 精确钉死：合法删除（退役文件户口）+
        改动落在活跃知识户口 → 第二循环挡住。
        touch 文件内容刻意与 del 不同：内容相同的 删+加 会被 git 判成改名
        （R100），--diff-filter=D 下删除集为空、门禁整体不激活——删除的口径是
        "内容真正消失"，移动由 rehome 自己的环路治理（见 tasks.py 门禁头注释）。"""
        head = self._commit_file("src/api/t59-mix-del.ini")
        self._register_file_household("knowledge.t59-mix", "src/api/t59-mix-del.ini")
        retire_household(self.root, card_id="knowledge.t59-mix", actor="test", reason="retire for mix test")
        register_household(
            self.root,
            card_id="knowledge.t59-mix-active",
            title="t59 mix active",
            summary="current household for touches-active pin",
            includes=["src/api/t59-mix-touch.ini"],
            excludes=[],
            floors=["floor.api"],
            capability="api",
            implementation="api.mix",
            status="current",
            grain="file",
            actor="test",
            reason="pin touches-active",
        )
        self._commit_file("src/api/t59-mix-touch.ini", content="touch\n")
        (self.root / "src/api/t59-mix-del.ini").unlink()
        try:
            with self.assertRaisesRegex(AG2CError, "^retirement-diff-touches-active"):
                self._gate(head, ["src/api/t59-mix-del.ini", "src/api/t59-mix-touch.ini"])
        finally:
            _git(self.root, "add", "--all")
            _git(self.root, "commit", "-m", "cleanup mix test")

    def test_current_knowledge_household_blocks_in_delete_loop(self):
        """活跃知识户口（status=current）在删除循环里直接挡：cannot-delete-active-household。"""
        head = self._commit_file("src/api/t59-cur.ini")
        register_household(
            self.root,
            card_id="knowledge.t59-cur",
            title="t59 cur",
            summary="current household covering the file",
            includes=["src/api/**"],
            excludes=[],
            floors=["floor.api"],
            capability="api",
            implementation="api.main",
            status="current",
            actor="test",
            reason="pin active-household block in delete loop",
        )
        (self.root / "src/api/t59-cur.ini").unlink()
        try:
            with self.assertRaisesRegex(AG2CError, "^cannot-delete-active-household:knowledge.t59-cur"):
                self._gate(head, ["src/api/t59-cur.ini"])
        finally:
            _git(self.root, "checkout", "--", "src/api/t59-cur.ini")

    def test_overlapping_current_file_household_still_blocks(self):
        """叠加口径：同路径一张退役（已确认）一张 current——活着的具体声明优先。"""
        head = self._commit_file("src/api/t59-duo.ini")
        self._register_file_household("knowledge.t59-duo-old", "src/api/t59-duo.ini")
        retire_household(self.root, card_id="knowledge.t59-duo-old", actor="test", reason="retire old file card")
        self._register_file_household("knowledge.t59-duo-new", "src/api/t59-duo.ini")
        (self.root / "src/api/t59-duo.ini").unlink()
        try:
            with self.assertRaisesRegex(AG2CError, "^cannot-delete-active-household:knowledge.t59-duo-new"):
                self._gate(head, ["src/api/t59-duo.ini"])
        finally:
            _git(self.root, "checkout", "--", "src/api/t59-duo.ini")

    def test_file_household_exclude_exact_file(self):
        """exclude 与 include 同口径：精确文件 exclude 落进 _exclude_roots 且生效。"""
        from ag2c.config import discover_manifest, load_manifest, load_policy
        from ag2c.households import _exclude_roots

        self._commit_file("src/api/t59-exc.ini")
        register_household(
            self.root,
            card_id="knowledge.t59-exc",
            title="t59 exc",
            summary="file household with exact-file exclude",
            includes=["src/api/t59-exc.ini"],
            excludes=["src/api/t59-exc.ini"],
            floors=["floor.api"],
            capability="api",
            implementation="api.exc",
            status="current",
            grain="file",
            actor="test",
            reason="exclude same-caliber test",
        )
        manifest = load_manifest(discover_manifest(self.root), project_root=self.root)
        policy = load_policy(manifest)
        card = next(c for c in policy.cards if c.card_id == "knowledge.t59-exc")
        self.assertIn(("app", "src/api/t59-exc.ini"), _exclude_roots(card))
        report = census_report(manifest, policy)
        covering = {h["id"] for h in households_covering_path(report, "app", "src/api/t59-exc.ini")}
        self.assertNotIn("knowledge.t59-exc", covering)

    def test_file_household_span_defaults_to_file(self):
        """画像推断落地：grain=file 未显式给 span 时默认 'file'（一文件一张）。"""
        from ag2c.config import discover_manifest, load_manifest, load_policy

        self._commit_file("t59-span.ini")
        self._register_file_household("knowledge.t59-span", "t59-span.ini")
        manifest = load_manifest(discover_manifest(self.root), project_root=self.root)
        card = next(c for c in load_policy(manifest).cards if c.card_id == "knowledge.t59-span")
        self.assertEqual("file", card.jurisdiction["span"])

    def test_directory_retirement_chain_regression(self):
        """目录退役链回归（画像④）：目录户口 retire → confirm → 删文件放行；
        legacy 无 replaced_by 仍挡。共用判定（_check_retired_household 重构）的回归面。
        用 tests/** 避开其他测试已登记的 src 目录户口（cannot-overlap-household）。"""
        head = self._commit_file("tests/t59-dir.ini")
        register_household(
            self.root,
            card_id="knowledge.t59-dir-ret",
            title="t59 dir ret",
            summary="directory household to retire",
            includes=["tests/**"],
            excludes=[],
            floors=["floor.api"],
            capability="tests",
            implementation="tests.dir",
            status="current",
            decider="confirm",
            actor="test",
            reason="directory retirement chain regression",
        )
        retire_household(self.root, card_id="knowledge.t59-dir-ret", actor="test", reason="retire dir")
        (self.root / "tests/t59-dir.ini").unlink()
        try:
            with self.assertRaisesRegex(AG2CError, "^retirement-confirm-required:knowledge.t59-dir-ret"):
                self._gate(head, ["tests/t59-dir.ini"])
            confirm_retirement(self.root, card_id="knowledge.t59-dir-ret", actor="test", reason="human fuse")
            self._gate(head, ["tests/t59-dir.ini"])  # 确认后放行
        finally:
            _git(self.root, "add", "--all")
            _git(self.root, "commit", "-m", "delete tests/t59-dir.ini")

        # legacy 无 replaced_by：手改 policy 构造（retire 命令本身拒绝这种态）。
        head2 = self._commit_file("tests/t59-legacy.ini")
        policy_path = self.root / ".ag2c" / "policy.json"
        raw = json.loads(policy_path.read_text(encoding="utf-8"))
        for card in raw["cards"]:
            if card["id"] == "knowledge.t59-dir-ret":
                card["jurisdiction"] = {**card["jurisdiction"], "status": "legacy"}
        policy_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        (self.root / "tests/t59-legacy.ini").unlink()
        try:
            with self.assertRaisesRegex(AG2CError, "^cannot-delete-without-replacement:knowledge.t59-dir-ret"):
                self._gate(head2, ["tests/t59-legacy.ini"])
        finally:
            _git(self.root, "checkout", "--", "tests/t59-legacy.ini")
            for card in raw["cards"]:
                if card["id"] == "knowledge.t59-dir-ret":
                    card["jurisdiction"] = {**card["jurisdiction"], "status": "retired"}
            policy_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    def test_unowned_delete_still_blocked(self):
        """无主文件删除仍挡：cannot-delete-unowned。"""
        head = self._commit_file("t59-orphan.ini")
        (self.root / "t59-orphan.ini").unlink()
        try:
            with self.assertRaisesRegex(AG2CError, "cannot-delete-unowned"):
                self._gate(head, ["t59-orphan.ini"])
        finally:
            _git(self.root, "checkout", "--", "t59-orphan.ini")

    def test_directory_household_semantics_unchanged(self):
        """目录户口回归：dir/** 正常登记；精确文件 include 仍被目录口径拒绝。"""
        register_household(
            self.root,
            card_id="knowledge.t59-dir",
            title="t59 dir",
            summary="directory household regression",
            includes=["src/worker/**"],
            excludes=[],
            floors=["floor.worker"],
            capability="worker",
            implementation="worker.main",
            status="current",
            actor="test",
            reason="directory semantics regression",
        )
        with self.assertRaises((AG2CError, ConfigurationError)):
            register_household(
                self.root,
                card_id="knowledge.t59-dirfile",
                title="t59 dirfile",
                summary="directory grain rejects exact file include",
                includes=["src/api/service.py"],
                excludes=[],
                floors=["floor.api"],
                capability="api",
                implementation="api.main",
                status="current",
                actor="test",
                reason="directory grain must reject file include",
            )


if __name__ == "__main__":
    unittest.main()
