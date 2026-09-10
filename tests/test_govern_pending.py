"""pending_updates 的 unowned-area 归属口径（t58）。

根文件：任意卡的精确 include（无 glob）或 references 收录即算有主——知识卡
认领根文件是合法登记（t56 布局缓存 ini 的教训：认领了却消不掉待办）。
根目录：口径不变，只有 floor 卡能认领。

冒烟集预算是硬约束（单模块 <=2.5s）：全类共享一个 git 夹具、一次 git add、
一次 pending_updates 调用，用 subTest 保持每条断言独立可定位——git 夹具
是这里唯一的重资源，摊薄它是留在 FAST 的唯一办法（监管者 t58 打回意见）。
"""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

import bootstrap  # noqa: F401

from ag2c.govern import pending_updates
from support import _git, git_project, write_project


def _knowledge_card(card_id: str, *, includes=(), references=()):
    return {
        "id": card_id,
        "type": "knowledge",
        "title": card_id,
        "summary": "Claims root file(s).",
        "scopes": [{"target": "app", "include": list(includes), "ownership": "reference"}],
        "references": list(references),
    }


class UnownedAreaSemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        cls.root = git_project(Path(cls._tmp.name) / "demo")
        write_project(cls.root)
        # 全部夹具文件一次入索引（ls-files 看索引，无需 commit）。
        for name, content in {
            "t58a.ini": "a\n",
            "t58b.ini": "b\n",
            "t58c-inc.ini": "c\n",
            "t58c-ref.ini": "c\n",
            "t58c-glob.ini": "c\n",
            "t58d-assets/a.txt": "d\n",
            "t58e.ini": "e\n",
        }.items():
            path = cls.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        _git(cls.root, "add", "t58a.ini", "t58b.ini", "t58c-inc.ini", "t58c-ref.ini",
             "t58c-glob.ini", "t58d-assets", "t58e.ini")

    def test_unowned_area_semantics(self):
        policy_path = self.root / ".ag2c" / "policy.json"
        base_text = policy_path.read_text(encoding="utf-8")
        raw = copy.deepcopy(json.loads(base_text))
        raw["cards"].extend(
            [
                # 主路：include + references 双收录（t56 布局缓存 ini 的实际形态）
                _knowledge_card("knowledge.t58a", includes=["t58a.ini"], references=["t58a.ini"]),
                # include-only：精确 include 单独成立
                _knowledge_card("knowledge.t58c-inc", includes=["t58c-inc.ini"]),
                # references-only：include 是无关 glob（校验要求 include 非空），
                # 认领完全由 references 承担
                _knowledge_card("knowledge.t58c-ref", includes=["elsewhere/**"], references=["t58c-ref.ini"]),
                # glob 反例：通配模式不算精确认领
                _knowledge_card("knowledge.t58c-glob", includes=["t58c-*.ini"]),
                # 目录反例：知识卡引用目录不算登记
                _knowledge_card("knowledge.t58d", includes=["t58d-assets"], references=["t58d-assets/a.txt"]),
                # floor 显式文件清单（floor.root 式现行主路）
                {
                    "id": "floor.t58e",
                    "type": "floor",
                    "title": "Root files",
                    "summary": "Owns tracked root files.",
                    "scopes": [{"target": "app", "include": ["t58e.ini"], "ownership": "primary"}],
                    "checkers": ["check.floor"],
                },
            ]
        )
        policy_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        try:
            items = pending_updates(self.root)["items"]
        finally:
            policy_path.write_text(base_text, encoding="utf-8")
        unowned = {item["path"] for item in items if item.get("kind") == "unowned-area"}

        with self.subTest(case="include+references 认领根文件 → 有主"):
            self.assertNotIn("t58a.ini", unowned)
        with self.subTest(case="无任何认领的根文件 → unowned"):
            self.assertIn("t58b.ini", unowned)
        with self.subTest(case="include-only 精确认领 → 有主"):
            self.assertNotIn("t58c-inc.ini", unowned)
        with self.subTest(case="references-only 认领 → 有主"):
            self.assertNotIn("t58c-ref.ini", unowned)
        with self.subTest(case="glob 模式不算精确认领 → unowned"):
            self.assertIn("t58c-glob.ini", unowned)
        with self.subTest(case="知识卡引用目录不算登记 → unowned"):
            self.assertIn("t58d-assets", unowned)
        with self.subTest(case="floor 显式文件清单 → 有主"):
            self.assertNotIn("t58e.ini", unowned)


if __name__ == "__main__":
    unittest.main()
