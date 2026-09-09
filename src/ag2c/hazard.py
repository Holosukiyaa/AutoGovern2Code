"""危房名单：把既有治理信号聚合成一张只读危楼清单，供市长看见哪些楼该修。

反向开发不是删代码，是合并同类、提高复用、顺便丢废弃。名单只负责"看得见"，
不动手。数据源全部已存在：
- 变异存活（最重）：账本 canary 事件里 mutation 演习未被拦住 → 该区域测试空心
- 查重警告：warning-history 的 possible-duplicate → 合并同类的机会
- 预算超标：warning-history 的 over-budget → 楼体肥胖
- 普查陈旧 / 过期卡片：census freshness=="stale" 的房间与 status=="stale" 的知识卡

与 patrol 同一条军规：任何输入异常都降级为空报告，绝不抛异常——看板必须在
项目出问题时也能渲染，因为那正是用户看它的时刻。
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .ledger import read_events
from .util import hidden_process_kwargs

HAZARD_SCHEMA = "ag2c.hazard.v1"

#: 严重度基线：hollow（安全网缺失，最危险）> duplicate（复用债）> budget（肥胖）> stale（档案旧）。
_KIND_WEIGHT = {"hollow": 40, "duplicate": 30, "budget": 20, "stale": 10}

#: 固定建议模板——制度在说话，不是 AI 自由文本。措辞规则：大白话+专业，
#: 单独拎出来无需懂城市隐喻即可理解。
SUGGESTIONS = {"hollow": "补充能捕获该类缺陷的测试", "duplicate": "合并重复实现", "budget": "精简或拆分", "stale": "重新普查确认"}

#: 变异描述里的文件定位，形如 "比较符 >→>=（src/ag2c_gui/graph.py:248）"。
_MUTATION_PATH = re.compile(r"（([^（）]+?):(\d+)）")

#: 警告历史的升级计数只影响同档内排序，封顶避免淹没种类权重。
_MAX_COUNT_BONUS = 5

#: 豁免登记的默认日落期：到期自动重现，防止"豁免了然后它真的烂了"。
DEFAULT_DISMISSAL_DAYS = 90

DISMISSAL_SCHEMA = "ag2c.hazard-dismissals.v1"


def _dismissals_path(manifest) -> Path:
    return manifest.state_dir / "hazard-dismissals.json"


def load_dismissals(manifest) -> list[dict[str, Any]]:
    """只读打开豁免登记；任何损坏都视为没有豁免（宁多报不漏报）。"""
    try:
        raw = json.loads(_dismissals_path(manifest).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(raw, dict) or not isinstance(raw.get("dismissals"), list):
        return []
    return [d for d in raw["dismissals"] if isinstance(d, dict)]


def _dismissal_active(dismissal: dict[str, Any], now: datetime) -> bool:
    """没有有效日落期的记录不可信：按已过期处理，让条目重新出现。"""
    expires = _parse_seen(dismissal.get("expires_at"))
    if expires is None:
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires > now


def dismiss_hazard(manifest, target: str, kind: str, *, actor: str, reason: str, days: int = DEFAULT_DISMISSAL_DAYS, now: datetime | None = None) -> dict[str, Any]:
    """豁免一条危房：审过、判定不拆，带理由与日落期。到期自动重现。

    豁免不是删除证据，是声明"这条我看过了"——豁免存量登上看板健康行，
    豁免太多等于市长在掩耳盗铃。同 target+kind 重复豁免视为续期（替换不堆叠）。"""
    from .errors import AG2CError
    from .ledger import append_event
    from .util import atomic_json_write

    target = str(target or "").strip()
    kind = str(kind or "").strip()
    if not target:
        raise AG2CError("hazard-dismiss requires a target")
    if kind not in _KIND_WEIGHT:
        raise AG2CError(f"unknown hazard kind: {kind!r}（可选：{', '.join(sorted(_KIND_WEIGHT))}）")
    if days < 1:
        raise AG2CError("dismissal days must be >= 1")
    now = now or datetime.now(timezone.utc)
    record = {
        "target": target,
        "kind": kind,
        "actor": actor,
        "reason": reason,
        "dismissed_at": now.isoformat(),
        "expires_at": (now + timedelta(days=days)).isoformat(),
    }
    dismissals = [d for d in load_dismissals(manifest) if not (d.get("target") == target and d.get("kind") == kind)]
    dismissals.append(record)
    atomic_json_write(_dismissals_path(manifest), {"schema": DISMISSAL_SCHEMA, "dismissals": dismissals})
    append_event(
        manifest.ledger_path,
        "hazard-dismiss",
        {"target": target, "kind": kind, "actor": actor, "reason": reason, "days": days, "expires_at": record["expires_at"]},
    )
    return record


def _mutation_target(text: object) -> tuple[str, int | None]:
    """从变异描述提取（文件路径, 行号）；提取不到返回空路径。"""
    if not isinstance(text, str):
        return "", None
    match = _MUTATION_PATH.search(text)
    if not match:
        return "", None
    return match.group(1).strip(), int(match.group(2))


def _hollow_hazards(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """变异存活 = 该区域测试空心。后续同文件演习通过则标注 resolved（疑似已修复）。"""
    survivors: dict[str, dict[str, Any]] = {}
    passed_files: set[str] = set()
    for event in events:
        if event.get("event_type") != "canary":
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if str(payload.get("mode") or "") != "mutation":
            continue
        path, line = _mutation_target(payload.get("mutation"))
        if not path:
            continue
        if str(payload.get("canary") or "") == "failed":
            survivors[path] = {
                "target": path,
                "kind": "hollow",
                "line": line,
                "detail": f"变异存活：{payload.get('mutation')}",
                "evidence": {"store": "ledger", "event": "canary", "at": event.get("occurred_at")},
                "resolved": False,
            }
        elif str(payload.get("canary") or "") == "passed":
            passed_files.add(path)
    hazards = []
    for path, entry in survivors.items():
        if path in passed_files:
            entry["resolved"] = True
            entry["detail"] += "（后续同文件演习已通过，疑似已修复）"
        hazards.append(entry)
    return hazards


def _load_warning_history(manifest) -> dict[str, Any]:
    """只读打开 state/warning-history.json；任何损坏都视为没有历史。"""
    try:
        raw = json.loads((manifest.state_dir / "warning-history.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict) or not isinstance(raw.get("warnings"), dict):
        return {}
    return raw["warnings"]


def _parse_seen(value: object) -> datetime | None:
    """解析 warning-history 的 ISO 时间戳；解析不了返回 None。"""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip())
    except ValueError:
        return None


def _file_last_commit(root: Path, relpath: str) -> datetime | None:
    """文件在 git 里的最后提交时间。查询失败返回 None——调用方按 standing 处理（宁多报不漏报）。"""
    try:
        proc = subprocess.run(
            ["git", "log", "-1", "--format=%cI", "--", relpath],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            **hidden_process_kwargs(),
        )
    except Exception:
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return _parse_seen(proc.stdout)


def _warning_freshness(last_seen: datetime | None, committed: datetime | None) -> str:
    """standing = 警告针对当前文件内容发出；unconfirmed = 文件在 last_seen 之后改过，记录可能已死。

    任一时间缺失都按 standing——保鲜机制只负责标注，不负责赦免。"""
    if last_seen is not None and committed is not None and last_seen < committed:
        return "unconfirmed"
    return "standing"


def _warning_hazards(manifest) -> list[dict[str, Any]]:
    """查重与预算警告：被无视的复用债与肥胖楼。count 越高同档内排越前。

    保鲜（2026-09-09）：警告历史是账本，只记"上次触发"，不记"是否已修复"。
    检测器是 HEAD 感知的，只有文件被改动才会重新评估——所以文件在 last_seen
    之后有过提交而警告没再触发，这条记录就降级为 unconfirmed（待复核），
    避免拆迁队照着死记录拆错楼。"""
    hazards = []
    commit_cache: dict[str, datetime | None] = {}
    for entry in _load_warning_history(manifest).values():
        if not isinstance(entry, dict):
            continue
        kind = {"possible-duplicate": "duplicate", "over-budget": "budget"}.get(str(entry.get("kind") or ""))
        if kind is None:
            continue
        key = str(entry.get("key") or entry.get("detail") or "")
        target = key.rsplit(":", 1)[0] if ":" in key else key
        count = int(entry.get("count") or 0)
        if target and target not in commit_cache:
            commit_cache[target] = _file_last_commit(manifest.project_root, target)
        hazards.append(
            {
                "target": target or key,
                "kind": kind,
                "count": count,
                "freshness": _warning_freshness(_parse_seen(entry.get("last_seen")), commit_cache.get(target)),
                "detail": str(entry.get("detail") or key),
                "evidence": {
                    "store": "warning-history",
                    "count": count,
                    "first_seen": entry.get("first_seen"),
                    "last_seen": entry.get("last_seen"),
                },
            }
        )
    return hazards


def _stale_hazards(manifest, policy) -> list[dict[str, Any]]:
    """普查陈旧的房间 + 过期的知识卡（日落条款）。需要 policy；缺席则跳过本源。"""
    if policy is None:
        return []
    hazards = []
    try:
        from .households import census_report

        for room in census_report(manifest, policy).get("households") or []:
            if isinstance(room, dict) and room.get("freshness") == "stale":
                hazards.append(
                    {
                        "target": str(room.get("id") or ""),
                        "kind": "stale",
                        "detail": "普查陈旧：房间声明与现状已漂移",
                        "evidence": {"store": "census", "freshness": "stale"},
                    }
                )
    except Exception:
        pass
    try:
        from .knowledge import knowledge_status

        for card in knowledge_status(manifest, policy):
            # 带 jurisdiction 的卡其状态派生自普查，上面已报，避免重复挂牌。
            if not isinstance(card, dict) or card.get("jurisdiction"):
                continue
            if card.get("status") == "stale":
                hazards.append(
                    {
                        "target": str(card.get("id") or ""),
                        "kind": "stale",
                        "detail": "知识卡过期：" + ", ".join(str(r) for r in card.get("reasons") or []),
                        "evidence": {"store": "knowledge", "reasons": card.get("reasons") or []},
                    }
                )
    except Exception:
        pass
    return hazards


def hazard_report(manifest, policy=None, *, now: datetime | None = None) -> dict[str, Any]:
    """汇总危房名单。任何输入异常都降级为空报告，绝不抛异常。"""
    now = now or datetime.now(timezone.utc)
    hazards: list[dict[str, Any]] = []
    try:
        events = read_events(manifest.ledger_path)
    except Exception:
        events = []
    try:
        hazards.extend(_hollow_hazards(events))
    except Exception:
        pass
    try:
        hazards.extend(_warning_hazards(manifest))
    except Exception:
        pass
    try:
        hazards.extend(_stale_hazards(manifest, policy))
    except Exception:
        pass
    try:
        dismissals = [d for d in load_dismissals(manifest) if _dismissal_active(d, now)]
    except Exception:
        dismissals = []
    if dismissals:
        dismissed_keys = {(str(d.get("target") or ""), str(d.get("kind") or "")) for d in dismissals}
        hazards = [h for h in hazards if (str(h.get("target") or ""), str(h.get("kind") or "")) not in dismissed_keys]
    for entry in hazards:
        kind = str(entry.get("kind") or "")
        entry["severity"] = _KIND_WEIGHT.get(kind, 0) + min(int(entry.get("count") or 0), _MAX_COUNT_BONUS)
        entry["suggestion"] = SUGGESTIONS.get(kind, "")
    hazards.sort(
        key=lambda item: (
            1 if item.get("freshness") == "unconfirmed" else 0,  # 待复核的排最后
            -int(item.get("severity") or 0),
            str(item.get("kind") or ""),
            str(item.get("target") or ""),
        )
    )
    counts: dict[str, int] = {}
    for entry in hazards:
        kind = str(entry.get("kind") or "")
        counts[kind] = counts.get(kind, 0) + 1
    return {
        "schema": HAZARD_SCHEMA,
        "generated_at": now.isoformat(),
        "hazards": hazards,
        "counts": counts,
        "dismissed": len(dismissals),
    }
