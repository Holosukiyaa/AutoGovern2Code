"""调度器 Phase 1：schedule() 影子模式（PROXY-GOVERNANCE.md 第 5/9 节）。

纯函数、零 I/O：从（本次计划的 checker、全部 checker、change_digest、账本事件）
算出「本会跳过什么」——但 Phase 1 不真跳。plan 作为 shadow_plan 附进 verify
记录与账本事件，让市长与监管观察数轮后再谈转正（Phase 2）。

铁律：跳过逻辑永远机械（只认 digest 与计划名单）、保守过包含；
skip 列表进报告给监管看。调度器自身的代码变更走 4.1 可信基仪式。
"""
from __future__ import annotations

from typing import Any

SHADOW_PLAN_SCHEMA = "ag2c.shadow-plan.v1"


def _passed_checker_ids(events: list[dict[str, Any]], change_digest: str) -> set[str]:
    """历史仓里的可复用证据：同 digest 的已通过 verify 里跑绿过的 checker 集合。"""
    reusable: set[str] = set()
    for event in events:
        if event.get("event_type") != "task-verification":
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if not payload.get("passed"):
            continue
        if str(payload.get("change_digest") or "") != change_digest:
            continue
        for item in payload.get("checker_results") or []:
            if isinstance(item, dict) and item.get("status") == "passed" and item.get("id"):
                reusable.add(str(item["id"]))
    return reusable


def shadow_plan(
    *,
    planned_checker_ids: list[str],
    all_checker_ids: list[str],
    change_digest: str,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    """影子计划：对每个 checker 给出 run/skip 决定与机械理由。

    - 未计划的 checker → skip（not-in-slice）：与今天的 route 一致，影子不发明新跳过；
    - 计划内但输入未变（同 digest 的历史全绿 verify 跑过它）→ skip（unchanged-inputs）：
      这是影子与现实唯一可能分叉的地方，也是 25 分钟病例里「重试全量重跑」的浪费点；
    - 其余 → run（slice-selected）。
    """
    planned_set = {str(item) for item in planned_checker_ids}
    reusable = _passed_checker_ids(events, change_digest)
    entries: list[dict[str, Any]] = []
    would_skip: list[str] = []
    for checker_id in [str(item) for item in all_checker_ids]:
        planned = checker_id in planned_set
        if not planned:
            entries.append({"id": checker_id, "planned": False, "shadow": "skip", "reasons": ["not-in-slice"]})
            continue
        if checker_id in reusable:
            entries.append({"id": checker_id, "planned": True, "shadow": "skip", "reasons": ["unchanged-inputs"]})
            would_skip.append(checker_id)
            continue
        entries.append({"id": checker_id, "planned": True, "shadow": "run", "reasons": ["slice-selected"]})
    return {
        "schema": SHADOW_PLAN_SCHEMA,
        "mode": "shadow",
        "change_digest": change_digest,
        "entries": entries,
        "would_skip": would_skip,
    }
