"""随机抽查计划：时间与对象随机生成，计划不出现在任何 AI 可见上下文。

Heartbleed 教训：审查机制若存在于被审查者的上下文里，被审查者就知道自己
何时被看着。因此：

- 计划只由用户侧进程生成（桌面端 project_details 路径）；verify / run_checks
  不生成、不读取、不展示。
- 计划落在 state 目录的 audit-state.json（数据目录，非仓库文件）；MCP 工具
  不提供任何读取入口，本模块不得被 mcp_server 引用。
- 对象随机：secrets 从房间卡与近期回执中抽取；时间随机：确认后 2-5 天内
  生成下一次计划。
- 抽查由人执行（核对卡片声明与实现是否一致），完成后在托盘确认；确认时间
  驱动「距上次抽查」健康度。
"""
from __future__ import annotations

import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

AUDIT_STATE_SCHEMA = "ag2c.audit-state.v1"
MIN_INTERVAL_DAYS = 2
MAX_INTERVAL_DAYS = 5
MAX_ROOM_PICKS = 3
RECEIPT_POOL = 20

_ROOM_QUESTION = "该房间卡声明与目录实际内容是否一致"
_RECEIPT_QUESTION = "该回执声明与实际提交是否一致"


def _state_path(manifest) -> Path:
    return manifest.path.parent / "audit-state.json"


def _default_state() -> dict[str, Any]:
    return {"schema": AUDIT_STATE_SCHEMA, "last_ack_at": None, "next_plan_at": None, "plan": None}


def _load_state(manifest) -> dict[str, Any]:
    try:
        state = json.loads(_state_path(manifest).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _default_state()
    if not isinstance(state, dict) or state.get("schema") != AUDIT_STATE_SCHEMA:
        return _default_state()
    return state


def _save_state(manifest, state: dict[str, Any]) -> None:
    path = _state_path(manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _room_card_ids(policy) -> list[str]:
    return sorted(
        card.card_id
        for card in policy.cards
        if card.card_type == "knowledge" and isinstance(card.jurisdiction, dict) and card.jurisdiction.get("span") == "folder"
    )


def _recent_receipt_ids(manifest) -> list[str]:
    directory = manifest.path.parent / "receipts"
    try:
        files = [path for path in directory.glob("*.json") if path.is_file()]
        files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    except OSError:
        return []
    return [path.stem for path in files[:RECEIPT_POOL]]


def _random_interval(now: datetime) -> datetime:
    return now + timedelta(days=MIN_INTERVAL_DAYS + secrets.randbelow(MAX_INTERVAL_DAYS - MIN_INTERVAL_DAYS + 1))


def _generate_plan(manifest, policy, now: datetime) -> dict[str, Any]:
    rng = secrets.SystemRandom()
    rooms = _room_card_ids(policy)
    items: list[dict[str, str]] = []
    if rooms:
        picks = min(len(rooms), 1 + secrets.randbelow(MAX_ROOM_PICKS))
        items.extend({"kind": "room-card", "id": room_id, "question": _ROOM_QUESTION} for room_id in rng.sample(rooms, picks))
    receipts = _recent_receipt_ids(manifest)
    if receipts:
        items.append({"kind": "receipt", "id": secrets.choice(receipts), "question": _RECEIPT_QUESTION})
    return {
        "id": uuid.uuid4().hex[:12],
        "created_at": _iso(now),
        "due_at": _iso(_random_interval(now)),
        "items": items,
        "acknowledged": False,
    }


def maybe_generate_plan(manifest, policy, *, now: datetime | None = None) -> dict[str, Any] | None:
    """用户侧入口：无活动计划且到达下次抽查时间时生成新计划。

    返回当前活动（未确认）计划；无活动计划时返回 None。verify 路径禁止调用。
    """
    now = now or _now()
    state = _load_state(manifest)
    plan = state.get("plan")
    if isinstance(plan, dict) and not plan.get("acknowledged"):
        return plan
    next_at = _parse(state.get("next_plan_at"))
    if next_at is not None and now < next_at:
        return None
    if not _room_card_ids(policy) and not _recent_receipt_ids(manifest):
        return None  # nothing worth auditing yet
    plan = _generate_plan(manifest, policy, now)
    state["plan"] = plan
    _save_state(manifest, state)
    return plan


def acknowledge(manifest, *, actor: str = "user", now: datetime | None = None) -> bool:
    """用户确认本轮抽查完成；随机排定下一次抽查时间。"""
    now = now or _now()
    state = _load_state(manifest)
    plan = state.get("plan")
    if not isinstance(plan, dict) or plan.get("acknowledged"):
        return False
    plan["acknowledged"] = True
    plan["acknowledged_by"] = actor
    plan["acknowledged_at"] = _iso(now)
    state["last_ack_at"] = _iso(now)
    state["next_plan_at"] = _iso(_random_interval(now))
    _save_state(manifest, state)
    return True


def audit_status(manifest, policy, *, now: datetime | None = None) -> dict[str, Any]:
    """用户侧状态：待抽查条目、是否到期、距上次确认天数。verify 路径禁止调用。"""
    now = now or _now()
    plan = maybe_generate_plan(manifest, policy, now=now)
    state = _load_state(manifest)
    last_ack = _parse(state.get("last_ack_at"))
    days_since = (now - last_ack).days if last_ack is not None else None
    pending: list[dict[str, str]] = []
    due = False
    if isinstance(plan, dict) and not plan.get("acknowledged"):
        pending = list(plan.get("items") or [])
        due_at = _parse(plan.get("due_at"))
        due = due_at is not None and now >= due_at
    return {"pending": pending, "due": due, "days_since": days_since}
