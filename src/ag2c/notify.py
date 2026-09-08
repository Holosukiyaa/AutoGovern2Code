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
