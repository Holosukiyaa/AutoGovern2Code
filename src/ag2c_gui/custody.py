"""托管桌：市长只剩看 / 否 / 授。不是 L0 总闸，也不是停止治理。"""
from __future__ import annotations

from typing import Any

from .dashboard import open_tasks, pending_items, stale_knowledge

_FLAGS = (
    ("auto_settle", "结算"),
    ("auto_census", "普查认领"),
    ("auto_warning", "良性警告认领"),
)
_WATCH = {"settle": "自动结算", "census": "自动普查认领", "warning": "自动认领警告"}
_IRREVERSIBLE = "合并、删除、放弃永不代理"
_SETTLE_KINDS = frozenset({"stale-knowledge"})
_CENSUS_KINDS = frozenset({"census-review-required"})


def _proxy_on(proxy: dict[str, Any], flag: str) -> bool:
    return proxy.get(flag) is True


def custody_model(details: dict[str, Any] | None, guard: dict[str, Any] | None = None) -> dict[str, Any]:
    """Mayor desk. Mechanical L0 items leave 否 when granted; merge never does."""
    blob = details if isinstance(details, dict) else {}
    guard = guard if isinstance(guard, dict) else {}
    project = blob.get("project") if isinstance(blob.get("project"), dict) else {}
    name = str(project.get("name") or "").strip()
    proxy = blob.get("proxy") if isinstance(blob.get("proxy"), dict) else {}
    flags = [{"id": fid, "label": label, "on": _proxy_on(proxy, fid)} for fid, label in _FLAGS]
    granted = any(item["on"] for item in flags)
    watch: list[dict[str, str]] = []
    for item in proxy.get("recent") or []:
        if not isinstance(item, dict):
            continue
        rule = str(item.get("rule") or "")
        watch.append({"rule": rule, "text": _WATCH.get(rule, rule or "代理决定"), "at": str(item.get("occurred_at") or "")})
    veto: list[dict[str, str]] = []
    if guard.get("canonicalDirty") and not guard.get("error"):
        veto.append({"id": "canonical-dirty", "kind": "p0", "text": "主干在非任务窗口被改了"})
    for task in open_tasks(blob):
        if task.get("diverged"):
            veto.append({"id": task["id"], "kind": "diverged", "text": f"任务 {task['id']} 已分叉"})
        elif task.get("lifecycle") in {"verified-unmerged", "verified-stale"}:
            veto.append({"id": task["id"], "kind": "merge", "text": f"任务 {task['id']} 已验证待合并"})
    settle_on, census_on = _proxy_on(proxy, "auto_settle"), _proxy_on(proxy, "auto_census")
    for item in pending_items(blob):
        kind = str(item.get("kind") or "")
        if kind in _CENSUS_KINDS and census_on:
            continue
        if kind in _SETTLE_KINDS and settle_on:
            continue
        title = str(item.get("title") or kind or "待办")
        veto.append({"id": str(item.get("path") or item.get("id") or title), "kind": kind or "pending", "text": title})
    if not settle_on:
        for card in stale_knowledge(blob):
            cid = str(card.get("id") or "")
            if cid and not any(row.get("id") == cid for row in veto):
                veto.append({"id": cid, "kind": "stale-knowledge", "text": f"知识卡过期：{cid}"})
    audit = blob.get("audit") if isinstance(blob.get("audit"), dict) else {}
    for item in audit.get("pending") or []:
        if isinstance(item, dict):
            veto.append({"id": str(item.get("id") or ""), "kind": "audit", "text": str(item.get("question") or "抽查")})
    if not name:
        headline = "先选择一个项目"
    elif not veto:
        headline = "刚才没有要你点的"
    else:
        headline = f"{len(veto)} 件要你点"
    return {
        "project": name,
        "empty": not bool(name),
        "headline": headline,
        "granted": granted,
        "flags": flags,
        "watch": watch,
        "veto": veto,
        "irreversible": _IRREVERSIBLE,
    }
