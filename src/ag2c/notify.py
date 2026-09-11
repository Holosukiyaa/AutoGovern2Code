"""门禁拦截通知队列：治理事件落盘，托盘轮询弹出。

设计原则：
- 纯文件 IO，无外部依赖。JSONL 追加写，托盘端按 offset 读。
- 每个项目一个文件，按 project_id 隔离。
- 通知是单向的：治理层写，托盘层读+确认。托盘不回复。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from .util import default_data_root

NOTIFICATION_SCHEMA = "ag2c.notification.v1"

# Kinds of notifications.
KIND_GATE_BLOCK = "gate-block"       # household gate / start gate blocked
KIND_VERIFY_FAIL = "verify-fail"     # verify checker failure
KIND_CANONICAL_DIRTY = "canonical-dirty"  # watchdog: canonical modified outside task
KIND_CENSUS_STALE = "census-stale"   # census freshness degraded
KIND_HAZARD = "hazard"               # P0 危房（severity≥50）首次出现/升级

_MAX_NOTIFICATIONS = 200  # ring buffer cap per project


def _notifications_dir() -> Path:
    return default_data_root() / "notifications"


def _queue_path(project_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in project_id)
    return _notifications_dir() / f"{safe}.jsonl"


def _read_queue(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    items: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                if isinstance(item, dict) and item.get("schema") == NOTIFICATION_SCHEMA:
                    items.append(item)
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return items


def _write_queue(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Ring buffer: keep only the latest N.
    if len(items) > _MAX_NOTIFICATIONS:
        items = items[-_MAX_NOTIFICATIONS:]
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in items) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def notify(
    project_id: str,
    kind: str,
    title: str,
    detail: str = "",
    *,
    task_id: str = "",
    room_id: str = "",
) -> dict[str, Any]:
    """Append a notification to the project's queue. Returns the notification."""
    notification = {
        "schema": NOTIFICATION_SCHEMA,
        "id": f"{int(time.time() * 1000)}-{os.getpid()}",
        "kind": kind,
        "title": title.strip(),
        "detail": detail.strip(),
        "task_id": task_id.strip(),
        "room_id": room_id.strip(),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "acknowledged": False,
    }
    path = _queue_path(project_id)
    items = _read_queue(path)
    items.append(notification)
    _write_queue(path, items)
    return notification


def pending_notifications(project_id: str) -> list[dict[str, Any]]:
    """Unacknowledged notifications for a project, oldest first."""
    return [item for item in _read_queue(_queue_path(project_id)) if not item.get("acknowledged")]


def acknowledge(project_id: str, notification_id: str) -> bool:
    """Mark one notification as read. Returns True if found."""
    path = _queue_path(project_id)
    items = _read_queue(path)
    found = False
    for item in items:
        if item.get("id") == notification_id and not item.get("acknowledged"):
            item["acknowledged"] = True
            found = True
    if found:
        _write_queue(path, items)
    return found


def acknowledge_all(project_id: str) -> int:
    """Mark all notifications as read. Returns count acknowledged."""
    path = _queue_path(project_id)
    items = _read_queue(path)
    count = 0
    for item in items:
        if not item.get("acknowledged"):
            item["acknowledged"] = True
            count += 1
    if count:
        _write_queue(path, items)
    return count


def notification_count(project_id: str) -> int:
    """Number of unacknowledged notifications."""
    return len(pending_notifications(project_id))


# --- 条件同步去重（sync_notification） ---
#
# 事件型通知（gate-block/verify-fail）每次发生都该弹；条件型通知
# （canonical-dirty/census-stale/hazard）是"某个条件当前为真"——条件持续为真
# 时每次检测都弹就是轰炸。sync_notification 按 key 记住"这个条件上次通报时
# 长什么样"：首现通知、level 升级再报、指纹变化再报、条件消失（active=False）
# 清除后再现重报。
#
# 状态由本模块自管（<project>.state.json），刻意不复用 checks.warning-history：
# 那台机器的计数会进 ESCALATABLE_KINDS 硬化成门，通知去重不该有门禁语义。

_DEDUP_SCHEMA = "ag2c.notification-state.v1"


def _dedup_path(project_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in project_id)
    return _notifications_dir() / f"{safe}.state.json"


def _read_dedup(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict) or not isinstance(raw.get("conditions"), dict):
        return {}
    return {str(k): v for k, v in raw["conditions"].items() if isinstance(v, dict)}


def _write_dedup(path: Path, conditions: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({"schema": _DEDUP_SCHEMA, "conditions": conditions}, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def sync_notification(
    project_id: str,
    key: str,
    *,
    active: bool,
    kind: str = "",
    title: str = "",
    detail: str = "",
    level: int = 0,
    fingerprint: str = "",
    task_id: str = "",
    room_id: str = "",
) -> dict[str, Any] | None:
    """同步一个条件的通知状态。active=False 清除去重键（条件消失）；
    active=True 时在首现/level 升级/指纹变化时发通知，否则静默。

    返回发出的通知；未发（去重或清除）返回 None。调用方负责 best-effort
    包裹——通知是观察通道，不是门禁。
    """
    key = str(key or "").strip()
    if not key:
        return None
    path = _dedup_path(project_id)
    conditions = _read_dedup(path)
    if not active:
        if key in conditions:
            conditions.pop(key, None)
            _write_dedup(path, conditions)
        return None
    previous = conditions.get(key)
    should_notify = (
        previous is None
        or int(level) > int(previous.get("level") or 0)
        or (fingerprint and fingerprint != str(previous.get("fingerprint") or ""))
    )
    conditions[key] = {
        "level": int(level),
        "fingerprint": str(fingerprint or ""),
        "last_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    _write_dedup(path, conditions)
    if not should_notify:
        return None
    return notify(project_id, kind, title, detail, task_id=task_id, room_id=room_id)


def prune_notification_conditions(project_id: str, prefix: str, keep: set[str]) -> list[str]:
    """清除 prefix 下不在 keep 里的去重键——条件集合整体同步的消失侧
    （如危房条目从名单消失）。返回被清除的 key。"""
    path = _dedup_path(project_id)
    conditions = _read_dedup(path)
    doomed = [key for key in conditions if key.startswith(prefix) and key not in keep]
    if doomed:
        for key in doomed:
            conditions.pop(key, None)
        _write_dedup(path, conditions)
    return sorted(doomed)
