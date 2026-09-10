"""动态房间预算：系统算，用户被告知。

预算的意义是禁止增长，不是惩罚现状——所以预算不该由人拍脑袋写进
policy，而由系统按普查实测自动锚定：

- 首次观察：budget = ceil(实测行数 × HEADROOM)，留 20% 增长余量；
- 房间缩小：预算自动收紧到新现状 × HEADROOM（棘轮只下不上，防反弹）；
- 房间增长但未超支：预算不动；
- 超支：预算不动，走既有 9.7 警告 → 升级 → 危房名单管线，人到那里决策；
- policy 里显式 budget_lines 的房间：人工预算优先，动态机制不碰。

告知渠道：每次重标写 budget-calibrated 账本事件；`ag2c govern
budget-recalibrate` 打印 实测/预算/动作 表；超支进危房名单。
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .ledger import append_event
from .model import Manifest, Policy
from .util import atomic_json_write, read_json

BUDGETS_SCHEMA = "ag2c.budgets.v1"
BUDGETS_FILENAME = "budgets.json"

#: 增长余量：预算 = 实测 × 1.2。定死为常量——余量该由治理共识调整，
#: 不该成为每个房间各自把玩的旋钮。
HEADROOM = 1.2


def budgets_path(manifest: Manifest) -> Path:
    return manifest.state_dir / BUDGETS_FILENAME


def load_budgets(manifest: Manifest) -> dict[str, Any]:
    """读动态预算仓。缺失/损坏一律降级为空仓——预算缺失只是不报警，绝不阻断。"""
    path = budgets_path(manifest)
    if not path.is_file():
        return {}
    try:
        value = read_json(path, what="dynamic budgets")
    except Exception:
        return {}
    if value.get("schema") != BUDGETS_SCHEMA:
        return {}
    rooms = value.get("rooms")
    return rooms if isinstance(rooms, dict) else {}


def _int_or_zero(value: Any) -> int:
    """预算仓字段容错：非数字（坏仓）一律降级为 0，绝不穿透到 verify。"""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def effective_budget_lines(manifest: Manifest, card) -> int:
    """有效行预算：policy 显式值优先，否则动态仓值，都没有则为 0（不报警）。"""
    explicit = _int_or_zero(getattr(card, "budget_lines", 0))
    if explicit > 0:
        return explicit
    entry = load_budgets(manifest).get(getattr(card, "card_id", ""))
    if isinstance(entry, dict):
        return _int_or_zero(entry.get("budget_lines"))
    return 0


def recalibrate_budgets(manifest: Manifest, policy: Policy, *, actor: str, reason: str, dry_run: bool = False) -> dict[str, Any]:
    """按普查实测重标动态预算。返回每房间的 实测/预算/动作 表（告知载体）。

    dry_run=True 只算表不落盘不写账本——裸 `ag2c govern budget-recalibrate`
    的预览模式；真正重标必须带 --actor/--reason（治理写入纪律）。
    """
    from .checks import _room_code_measurements
    from .households import census_report

    actor = actor.strip()
    reason = reason.strip()
    if not dry_run and (not actor or not reason):
        from .errors import AG2CError

        raise AG2CError("budget recalibration requires --actor and --reason")
    store = load_budgets(manifest)
    try:
        report = census_report(manifest, policy)
    except Exception:
        report = {"households": []}
    rows: list[dict[str, Any]] = []
    changed = False
    for item in report.get("households") or []:
        if not isinstance(item, dict):
            continue
        room = str(item.get("id") or "")
        if not room:
            continue
        try:
            card = policy.card(room)
        except StopIteration:
            card = None
        if card is not None and _int_or_zero(getattr(card, "budget_lines", 0)) > 0:
            continue  # 人工显式预算优先，动态机制不碰
        measured = int(_room_code_measurements(manifest, item)["lines"])
        if measured <= 0:
            continue  # 空房间不定预算（0 在警告侧是"不报警"语义）
        derived = math.ceil(measured * HEADROOM)
        previous = store.get(room)
        previous_budget = _int_or_zero(previous.get("budget_lines")) if isinstance(previous, dict) else 0
        if previous_budget <= 0:
            action, budget = "set", derived
        elif derived < previous_budget:
            action, budget = "tightened", derived  # 棘轮只下不上
        else:
            action, budget = "kept", previous_budget
        rows.append({"room": room, "measured_lines": measured, "budget_lines": budget, "previous_lines": previous_budget, "action": action})
        if action != "kept" and not dry_run:
            store[room] = {
                "budget_lines": budget,
                "measured_lines": measured,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "actor": actor,
                "reason": reason,
            }
            append_event(
                manifest.ledger_path,
                "budget-calibrated",
                {"room": room, "action": action, "measured_lines": measured, "budget_lines": budget, "previous_lines": previous_budget, "actor": actor, "reason": reason},
            )
            changed = True
    if changed:
        atomic_json_write(budgets_path(manifest), {"schema": BUDGETS_SCHEMA, "rooms": store})
    return {"schema": BUDGETS_SCHEMA, "rooms": rows}
