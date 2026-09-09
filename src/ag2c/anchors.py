"""provides 证据锚：把知识卡的能力清单从散文变成可验证断言。

知识卡片是 AI 写的散文，用户读卡片代替读代码；普查只查新鲜度（文件变了没），
不查真实性（内容是否符合代码语义）。一张写着"此模块提供 X 能力"的卡片如果
对应代码里根本没有 X，用户的心智地图就被俘虏。本模块把 provides 条目锚定到
references 指向的 Python 文件里真实存在的顶层符号（函数/类/常量，AST 解析，
不 import）：

- govern apply 新增/修改 provides 时：锚错即拒绝（写新卡就必须锚对）
- 存量卡：census_report 输出 anchor_warnings，run_checks 接入 warning-history
  （kind=provides-anchor，不阻断、不参与 9.7 升级，给存量留迁移期）

降级军规：非 Python 房间、references 缺失、AST 解析失败等情况一律跳过校验
（不报错），宁缺毋滥。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

#: provides 条目里的符号候选：散文中的 Python 标识符（中文修饰语自然被排除）。
_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

#: warning-history 里的警告种类。刻意不加入 checks.ESCALATABLE_KINDS：存量迁移期不升级。
ANCHOR_WARNING_KIND = "provides-anchor"


def _top_level_symbols(path: Path) -> set[str] | None:
    """AST 解析文件的顶层定义（函数/类/赋值常量）。读取或解析失败返回 None。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return None
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def anchor_violations(root: Path, provides: list[str], references: list[str]) -> list[str]:
    """返回未能锚定的 provides 条目（原样返回，保持卡片上的措辞）。

    条目锚定的判定：条目里至少一个标识符是 references 文件里的顶层定义。
    降级军规（返回空 = 跳过校验）：provides/references 为空、没有 .py 引用、
    任一引用文件读取或 AST 解析失败、文件没有任何顶层定义。
    """
    if not provides or not references:
        return []
    py_refs = [str(ref) for ref in references if str(ref).endswith(".py")]
    if not py_refs:
        return []
    symbols: set[str] = set()
    for ref in py_refs:
        found = _top_level_symbols(root / ref)
        if found is None:
            return []
        symbols |= found
    if not symbols:
        return []
    violations = []
    for entry in provides:
        tokens = set(_TOKEN.findall(str(entry)))
        if not tokens or tokens.isdisjoint(symbols):
            violations.append(str(entry))
    return violations


def provides_anchor_warnings(manifest, policy, *, card_ids: set[str] | None = None) -> list[dict[str, Any]]:
    """存量卡巡检：对带 provides 的知识卡逐张锚定，返回 warning 列表，绝不抛异常。

    card_ids 给定时只巡检这些卡（run_checks 按切片卡 scoped）；否则全量（census）。
    """
    warnings: list[dict[str, Any]] = []
    try:
        root = manifest.project_root
        for card in policy.cards:
            if card.card_type != "knowledge" or not card.provides:
                continue
            if card_ids is not None and card.card_id not in card_ids:
                continue
            bad = anchor_violations(root, list(card.provides), list(card.references))
            if bad:
                warnings.append(
                    {
                        "kind": ANCHOR_WARNING_KIND,
                        "key": card.card_id,
                        "detail": "provides 未锚定到 references 的真实符号: "
                        + "; ".join(bad[:3])
                        + (" …" if len(bad) > 3 else ""),
                    }
                )
    except Exception:
        return []
    return warnings
