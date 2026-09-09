"""巡逻报告：从账本读出治理系统的巡逻叙事，供市长看板呈现。

市长不巡检，市长看巡逻记录。本模块把账本里的治理事件翻译成城市语言：
- 安检演习（gate 金丝雀）：派人带违禁品过安检，必须被拦
- 消防演习（mutation 金丝雀）：楼里放把小火，喷淋必须启动
- 拦截通报（violation-blocked）：有人试图绕过流程，被门卫拦下

演习超期（从未演习或超过 DRILL_INTERVAL_DAYS 天）本身就是警情：
巡逻队不巡逻，等于没有巡逻队。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .ledger import read_events

#: 演习间隔（天）。V1 常量；未来可入 policy 按项目调节。
DRILL_INTERVAL_DAYS = 7

#: 拦截通报的统计窗口（天）。
INTERCEPTION_WINDOW_DAYS = 30

_DRILL_LABELS = {"gate": "安检演习", "mutation": "消防演习"}


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _days_since(moment: datetime | None, now: datetime) -> int | None:
    if moment is None:
        return None
    return max(0, (now - moment).days)


def patrol_report(manifest, *, now: datetime | None = None) -> dict[str, Any]:
    """汇总账本里的巡逻事件。账本缺失或损坏时降级为空报告，绝不抛异常——
    看板必须在项目出问题时也能渲染，因为那正是用户看它的时刻。"""
    now = now or datetime.now(timezone.utc)
    drills: dict[str, dict[str, Any]] = {}
    interceptions: list[dict[str, Any]] = []
    try:
        events = read_events(manifest.ledger_path)
    except Exception:
        events = []
    for event in events:
        occurred = _parse_time(event.get("occurred_at"))
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if event.get("event_type") == "canary":
            mode = str(payload.get("mode") or "gate")
            entry = drills.setdefault(mode, {"runs": 0})
            entry["runs"] = int(entry.get("runs") or 0) + 1
            entry["last_at"] = event.get("occurred_at")
            entry["last_result"] = str(payload.get("canary") or "unknown")
            entry["last_detail"] = str(payload.get("mutation") or payload.get("reason") or "")
            entry["days_since"] = _days_since(occurred, now)
        elif event.get("event_type") == "violation-blocked":
            interceptions.append(
                {
                    "at": event.get("occurred_at"),
                    "kind": str(payload.get("kind") or "unknown"),
                    "days_since": _days_since(occurred, now),
                }
            )
    for mode, label in _DRILL_LABELS.items():
        entry = drills.setdefault(mode, {"runs": 0, "last_at": None, "last_result": None, "days_since": None})
        entry["label"] = label
        days = entry.get("days_since")
        entry["overdue"] = days is None or days > DRILL_INTERVAL_DAYS
    recent_interceptions = [item for item in interceptions if (item["days_since"] or 0) <= INTERCEPTION_WINDOW_DAYS]
    return {
        "schema": "ag2c.patrol.v1",
        "drills": drills,
        "interceptions": {
            "total": len(interceptions),
            "window_days": INTERCEPTION_WINDOW_DAYS,
            "in_window": len(recent_interceptions),
            "recent": interceptions[-5:],
        },
        "drill_interval_days": DRILL_INTERVAL_DAYS,
    }
