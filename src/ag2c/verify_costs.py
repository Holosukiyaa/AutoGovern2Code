"""验证成本治理：verify 自身的预算与计量。

治理系统不治理自己的验证通道，验证成本就会淤积——常开地板门只增不减。
本模块把 checker 耗时变成可查询、可预算的一等数据：

- 计量：checker 耗时本就在账本 check-run 事件的 results 里（duration_ms），
  checker_duration_history 把它变成可查询的每 checker 历史序列；
- 预算：复用 budgets.py 的动态预算模式——首锚 ceil(实测 × HEADROOM)、
  棘轮只紧不松、policy 显式 budget_seconds 优先、无历史/坏仓不报警；
  实测基准取近 HISTORY_WINDOW 次的最大值（时间测量噪声大，最近一次的
  快运行会锚出低预算然后误报——警报疲劳是所有信号的死亡）；
- 超支：产出 kind="over-budget" 警告（key 形如 check.python:seconds），
  自动进入 9.7 警告 → 升级 → 危房名单管道，人到那里决策。

告知渠道：settle 自动重标并写 verify-budget-calibrated 账本事件；
`ag2c govern verify-budget` 裸命令打印 实测/预算/动作 预览表。
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .ledger import append_event, read_events
from .model import Manifest, Policy
from .util import atomic_json_write, read_json

VERIFY_BUDGETS_SCHEMA = "ag2c.verify-budgets.v1"
VERIFY_BUDGETS_FILENAME = "verify-budgets.json"

#: 时间预算的增长余量：比行数预算的 1.2 宽——checker 耗时受机器负载与并行
#: 打包影响，实测波动大（t33 并行竞争下 fast 套件曾从 120s 冲到 300s）。
VERIFY_HEADROOM = 1.5

#: 实测基准窗口：取最近 N 次观察的最大值作为"实测"。
HISTORY_WINDOW = 5

#: 最小预算：低于此值不定预算——秒级以下的小 checker 报警全是噪声。
MIN_BUDGET_SECONDS = 5


def verify_budgets_path(manifest: Manifest) -> Path:
    return manifest.state_dir / VERIFY_BUDGETS_FILENAME


def load_verify_budgets(manifest: Manifest) -> dict[str, Any]:
    """读验证预算仓。缺失/损坏一律降级为空仓——预算缺失只是不报警，绝不阻断。"""
    path = verify_budgets_path(manifest)
    if not path.is_file():
        return {}
    try:
        value = read_json(path, what="verify budgets")
    except Exception:
        return {}
    if value.get("schema") != VERIFY_BUDGETS_SCHEMA:
        return {}
    checkers = value.get("checkers")
    return checkers if isinstance(checkers, dict) else {}


def _seconds_or_zero(value: Any) -> float:
    """预算仓字段容错：非数字（坏仓）一律降级为 0，绝不穿透到 verify。"""
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def checker_duration_history(manifest: Manifest) -> dict[str, list[float]]:
    """从账本 check-run 事件查询每 checker 的耗时历史（秒，按时间升序）。

    账本损坏或没有 check-run 事件时降级为空表——没有历史不定预算。
    """
    try:
        events = read_events(manifest.ledger_path)
    except Exception:
        return {}
    history: dict[str, list[float]] = {}
    for event in events:
        if not isinstance(event, dict) or event.get("event_type") != "check-run":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        for result in payload.get("results") or []:
            if not isinstance(result, dict):
                continue
            checker_id = str(result.get("id") or "")
            duration_ms = result.get("duration_ms")
            if not checker_id or not isinstance(duration_ms, (int, float)) or duration_ms <= 0:
                continue
            history.setdefault(checker_id, []).append(duration_ms / 1000.0)
    return history


def measured_seconds(history: list[float]) -> float:
    """实测基准：最近 HISTORY_WINDOW 次观察的最大值（噪声上界，防误报）。"""
    recent = [value for value in history if value > 0][-HISTORY_WINDOW:]
    return max(recent) if recent else 0.0


def effective_budget_seconds(manifest: Manifest, checker) -> float:
    """有效秒预算：policy 显式 budget_seconds 优先，否则动态仓值，都没有则为 0（不报警）。"""
    explicit = _seconds_or_zero(getattr(checker, "budget_seconds", 0))
    if explicit > 0:
        return explicit
    entry = load_verify_budgets(manifest).get(getattr(checker, "checker_id", ""))
    if isinstance(entry, dict):
        return _seconds_or_zero(entry.get("budget_seconds"))
    return 0.0


#: 硬杀倍率：动态预算是淤积警告线（实测×1.5），硬杀线再放宽一倍量级。
#: timeout 的职责是抓挂死，不是执法性能——性能归 over-budget 警告管。
TIMEOUT_KILL_FACTOR = 3.0


def effective_timeout_seconds(manifest: Manifest, checker, *, parallelism: int = 1) -> float:
    """有效硬杀超时：动态秒预算 × KILL_FACTOR × 并行度；无锚定回退 静态 timeout × 并行度。

    单源原则（2026-09-10 P0）：静态 checker.timeout 是拍值，动态预算仓是实测。
    过去两个旋钮互不相识——并行度调到 4 后全量 verify 九套件互拖，全部撞静态
    上限假性失败（exit_code=null、耗时恰等于上限），同代码串行全绿。硬杀线
    改从实测派生并与警告线同源同漂移；并行时按 workers 线性放大——它抓的是
    挂死，宁可宽松不可误杀，性能劣化由预算警告线提前报警。
    """
    budget = effective_budget_seconds(manifest, checker)
    base = budget * TIMEOUT_KILL_FACTOR if budget > 0 else _seconds_or_zero(getattr(checker, "timeout", 0))
    return base * max(1, int(parallelism))


def verify_budget_warnings(manifest: Manifest, policy: Policy, results: list[dict[str, Any]]) -> list[dict[str, str]]:
    """verify 超支警告：checker 实测耗时超过有效预算时产出 over-budget 警告。

    预算为 0（未锚定/坏仓）的 checker 不报警——预算的意义是禁止增长，
    不是惩罚现状；没有预算就没有现状可罚。
    """
    budgets = load_verify_budgets(manifest)
    if not budgets and not any(_seconds_or_zero(getattr(checker, "budget_seconds", 0)) > 0 for checker in policy.checkers):
        return []
    warnings: list[dict[str, str]] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        checker_id = str(result.get("id") or "")
        duration_ms = result.get("duration_ms")
        if not checker_id or not isinstance(duration_ms, (int, float)) or duration_ms <= 0:
            continue
        checker = next((item for item in policy.checkers if item.checker_id == checker_id), None)
        if checker is None:
            continue
        budget = effective_budget_seconds(manifest, checker)
        actual = duration_ms / 1000.0
        if budget > 0 and actual > budget:
            warnings.append(
                {
                    "kind": "over-budget",
                    "key": f"{checker_id}:seconds",
                    "detail": f"checker {checker_id} 本次耗时 {actual:.1f}s，超出验证预算 {budget:.0f}s——验证通道在淤积，考虑瘦身/拆分/下沉房间套件",
                }
            )
    return warnings


def recalibrate_verify_budgets(manifest: Manifest, policy: Policy, *, actor: str, reason: str, dry_run: bool = False) -> dict[str, Any]:
    """按账本耗时历史重标验证预算。返回每 checker 的 实测/预算/动作 表（告知载体）。

    dry_run=True 只算表不落盘不写账本——裸 `ag2c govern verify-budget`
    的预览模式；真正重标必须带 --actor/--reason（治理写入纪律）。
    """
    from .errors import AG2CError

    actor = actor.strip()
    reason = reason.strip()
    if not dry_run and (not actor or not reason):
        raise AG2CError("verify budget recalibration requires --actor and --reason")
    store = load_verify_budgets(manifest)
    history = checker_duration_history(manifest)
    rows: list[dict[str, Any]] = []
    changed = False
    for checker in policy.checkers:
        if _seconds_or_zero(getattr(checker, "budget_seconds", 0)) > 0:
            continue  # 人工显式预算优先，动态机制不碰
        measured = measured_seconds(history.get(checker.checker_id, []))
        if measured <= 0:
            continue  # 无历史不定预算（0 在警告侧是"不报警"语义）
        derived = max(MIN_BUDGET_SECONDS, math.ceil(measured * VERIFY_HEADROOM))
        previous = store.get(checker.checker_id)
        previous_budget = _seconds_or_zero(previous.get("budget_seconds")) if isinstance(previous, dict) else 0.0
        if previous_budget <= 0:
            action, budget = "set", float(derived)
        elif derived < previous_budget:
            action, budget = "tightened", float(derived)  # 棘轮只下不上
        else:
            action, budget = "kept", previous_budget
        rows.append(
            {
                "checker": checker.checker_id,
                "measured_seconds": round(measured, 1),
                "budget_seconds": budget,
                "previous_seconds": previous_budget,
                "action": action,
            }
        )
        if action != "kept" and not dry_run:
            store[checker.checker_id] = {
                "budget_seconds": budget,
                "measured_seconds": round(measured, 1),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "actor": actor,
                "reason": reason,
            }
            append_event(
                manifest.ledger_path,
                "verify-budget-calibrated",
                {"checker": checker.checker_id, "action": action, "measured_seconds": round(measured, 1), "budget_seconds": budget, "previous_seconds": previous_budget, "actor": actor, "reason": reason},
            )
            changed = True
    if changed:
        atomic_json_write(verify_budgets_path(manifest), {"schema": VERIFY_BUDGETS_SCHEMA, "checkers": store})
    return {"schema": VERIFY_BUDGETS_SCHEMA, "checkers": rows}
