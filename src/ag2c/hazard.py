"""危房名单：把既有治理信号聚合成一张只读危楼清单，供市长看见哪些楼该修。

反向开发不是删代码，是合并同类、提高复用、顺便丢废弃。名单只负责"看得见"，
不动手。数据源全部已存在：
- 变异存活（最重）：账本 canary 事件里 mutation 演习未被拦住 → 该区域测试空心
- 查重警告：warning-history 的 possible-duplicate → 合并同类的机会
- 预算超标：warning-history 的 over-budget → 楼体肥胖
- 普查陈旧 / 过期卡片：census freshness=="stale" 的房间与 status=="stale" 的知识卡
- 监管缺席（最重）：账本 task-verification 事件里连续 N 次 regulator unavailable
  （已配置却拿不到裁决）→ 最像"验证"的验证在静默缺席（4.3：沉默本身即警情）
- 守卫拆除（最重）：core.hooksPath 偏离本 store 的 state/hooks 或目录失踪
  → 门禁形同虚设的当下即报警，不等事后（4.4：沉默本身即警情）
- 无 trailer 提交：治理存在后落在主干、没有 AG2C-Task trailer 的提交
  → 绕开结果门的活动；市长直推也上榜，hazard-dismiss 是认领通道（4.4 事后审计）

与 patrol 同一条军规：任何输入异常都降级为空报告，绝不抛异常——看板必须在
项目出问题时也能渲染，因为那正是用户看它的时刻。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .ledger import read_events
from .util import hidden_process_kwargs

HAZARD_SCHEMA = "ag2c.hazard.v1"

#: 严重度基线：guard-removed（守卫被拆，一切门禁形同虚设）> regulator-absent
#: （监管静默缺席，验证形同虚设）> ungoverned-commit（无 trailer 提交绕开结果门）
#: > hollow（安全网缺失）> duplicate（复用债）> budget（肥胖）> stale（档案旧）。
_KIND_WEIGHT = {"guard-removed": 60, "regulator-absent": 50, "ungoverned-commit": 45, "hollow": 40, "duplicate": 30, "budget": 20, "stale": 10}

#: 固定建议模板——制度在说话，不是 AI 自由文本。措辞规则：大白话+专业，
#: 单独拎出来无需懂城市隐喻即可理解。
SUGGESTIONS = {"guard-removed": "重新 enroll 恢复守卫；确认是刻意拆除则用 govern hazard-dismiss 登记", "regulator-absent": "检查监管端点与密钥；或显式 govern regulator --strict off 承认降级", "ungoverned-commit": "确认提交来源；市长直推用 govern hazard-dismiss 认领，否则追查守卫去向", "hollow": "补充能捕获该类缺陷的测试", "duplicate": "合并重复实现", "budget": "精简或拆分", "stale": "重新普查确认"}

#: 监管缺席升级阈值：连续这么多次 verify 没拿到裁决才进名单（偶发网络抖动不报）。
_REGULATOR_ABSENT_THRESHOLD = 3

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


def _regulator_absent_hazards(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """监管静默缺席：从最新 verify 往回数，连续 unavailable（已配置却拿不到裁决）达到阈值才报警。

    not-configured（用户从未配置监管）不算缺席——未配置是配置状态，配置了却
    拿不到才是警情；passed/rejected 都证明监管在线，打断计数。
    """
    consecutive = 0
    captured = False
    last_reason = ""
    last_at = ""
    for event in reversed(events):
        if event.get("event_type") != "task-verification":
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        regulator = payload.get("regulator") if isinstance(payload.get("regulator"), dict) else {}
        outcome = str(regulator.get("outcome") or "")
        reason = str(regulator.get("reason") or "")
        if outcome == "unavailable" and reason != "not-configured":
            consecutive += 1
            if not captured:
                # 独立哨兵：最新样本的 occurred_at 可能为空，不能用 last_at
                # 的真值当“已捕获”标志，否则更旧事件的 reason 会覆盖进来。
                captured = True
                last_reason = reason
                last_at = str(event.get("occurred_at") or "")
            continue
        break
    if consecutive < _REGULATOR_ABSENT_THRESHOLD:
        return []
    return [
        {
            "target": "regulator",
            "kind": "regulator-absent",
            "count": consecutive,
            "detail": f"连续 {consecutive} 次 verify 缺 AI 监管（最近原因：{last_reason}）",
            "evidence": {"store": "ledger", "event": "task-verification", "at": last_at},
        }
    ]


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


def _git_output(root: Path, *args: str) -> str | None:
    """跑一次只读 git；任何失败返回 None（调用方按降级处理，宁多报不漏报的另一面是不炸看板）。"""
    try:
        proc = subprocess.run(
            ["git", *args],
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
    if proc.returncode != 0:
        return None
    return proc.stdout


def _guard_hazards(manifest) -> list[dict[str, Any]]:
    """守卫心跳（4.4）：core.hooksPath 必须指向本 store 的 state/hooks 且目录在。

    一条 git config 即可拆守卫——拆除当下就是警情，不等事后审计。
    门槛是 activation.json（纳管登记）：未纳管的项目没有守卫可拆，不报。"""
    try:
        if not (manifest.state_dir / "activation.json").is_file():
            return []
        expected = str((manifest.state_dir / "hooks").resolve())
        actual = str(_git_output(manifest.project_root, "config", "--get", "core.hooksPath") or "").strip()
        if os.path.normcase(actual) == os.path.normcase(expected) and Path(expected).is_dir():
            return []
        if not actual:
            detail = f"守卫已拆：core.hooksPath 未设置，应为 {expected}"
        elif os.path.normcase(actual) != os.path.normcase(expected):
            detail = f"守卫已拆：core.hooksPath={actual}，应为 {expected}"
        else:
            detail = f"守卫已拆：hooks 目录失踪（{expected}）"
        return [
            {
                "target": "core.hooksPath",
                "kind": "guard-removed",
                "detail": detail,
                "evidence": {"store": "git-config", "expected": expected, "actual": actual},
            }
        ]
    except Exception:
        return []


#: 无 trailer 审计的扫描上限（提交数）。治理后的提交实务上远少于此；上限防历史洪水。
_UNGOVERNED_SCAN_CAP = 500


def _ungoverned_commit_hazards(manifest, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """trunk 无 trailer 提交的事后审计（4.4）：治理存在之后落在主干、却没有
    AG2C-Task trailer 的提交 = 绕开结果门的活动。

    市长直推也上榜——系统无法区分市长与拆守卫的攻击者，hazard-dismiss 登记
    豁免就是市长的认领通道。基线取账本首事件：治理存在之前的提交没有可治理性。
    门槛是 activation.json（纳管登记）：未纳管的项目谈不上"绕开"守卫。
    """
    trunk = str(getattr(manifest, "trunk", "") or "").strip()
    if not trunk:
        return []
    if not (manifest.state_dir / "activation.json").is_file():
        return []
    baseline = next((str(event.get("occurred_at")) for event in events if event.get("occurred_at")), "")
    if not baseline:
        return []
    raw = _git_output(
        manifest.project_root,
        "log",
        trunk,
        f"--since={baseline}",
        f"-n{_UNGOVERNED_SCAN_CAP}",
        "--format=%H%x1f%cI%x1f%an%x1f%B%x1e",
    )
    if not raw:
        return []
    hazards: list[dict[str, Any]] = []
    for record in raw.split("\x1e"):
        parts = record.strip("\n").split("\x1f", 3)
        if len(parts) != 4 or not parts[0].strip():
            continue
        sha, committed_at, author, message = parts[0].strip(), parts[1].strip(), parts[2].strip(), parts[3]
        if "AG2C-Task:" in message:
            continue
        subject = message.strip().splitlines()[0] if message.strip() else ""
        hazards.append(
            {
                "target": sha[:12],
                "kind": "ungoverned-commit",
                "detail": f"无 AG2C-Task trailer 的主干提交：{subject}（{author}）",
                "evidence": {"store": "git", "commit": sha, "at": committed_at},
            }
        )
    return hazards


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


def _is_test_path(rel: str) -> bool:
    """路径是否属于测试代码（tests/ 目录或 test_ 前缀文件）。"""
    parts = str(rel).replace("\\", "/").split("/")
    return "tests" in parts or parts[-1].startswith("test_")


def _warning_hazards(manifest) -> list[dict[str, Any]]:
    """查重与预算警告：被无视的复用债与肥胖楼。count 越高同档内排越前。

    保鲜（2026-09-09）：警告历史是账本，只记"上次触发"，不记"是否已修复"。
    检测器是 HEAD 感知的，只有文件被改动才会重新评估——所以文件在 last_seen
    之后有过提交而警告没再触发，这条记录就降级为 unconfirmed（待复核），
    避免拆迁队照着死记录拆错楼。

    校准（2026-09-10）：查重区改为现行配对规则的全仓实时扫描
    （checks.scan_duplicate_pairs），warning-history 只贡献 count/first_seen
    排序依据。旧探测器时代的化石记录（规则已收紧、不再复现）自动消失——
    拆迁队列只列当下仍为真的重复。预算区维持历史驱动（预算超标是房间级
    状态，没有等价的实时配对扫描）。"""
    from .checks import scan_duplicate_pairs

    history = _load_warning_history(manifest)
    hazards: list[dict[str, Any]] = []
    commit_cache: dict[str, datetime | None] = {}

    # 查重：实时扫描为骨，历史计数为翼。扫描失败不连累预算区。
    # 双测试文件的相似对不进拆迁队列：测试的镜像结构是表驱动写法常态，
    # 拆迁对象是产品代码；测试重复由 diff 探测器在新增时把关。
    try:
        pairs = [
            pair
            for pair in scan_duplicate_pairs(manifest)
            if not (_is_test_path(pair["file"]) and _is_test_path(pair["other_file"]))
        ]
    except Exception:
        pairs = []
    dupe_history: dict[str, dict[str, Any]] = {}
    for entry in history.values():
        if isinstance(entry, dict) and str(entry.get("kind") or "") == "possible-duplicate":
            dupe_history[str(entry.get("key") or "")] = entry
    for pair in pairs:
        key = f"{pair['file']}:{pair['name']}"
        record = dupe_history.get(key) or dupe_history.get(f"{pair['other_file']}:{pair['other_name']}") or {}
        count = int(record.get("count") or 0)
        if pair["match"] == "同名":
            detail = f"同名函数 {pair['name']}（{pair['file']}）与 {pair['other_file']} 参数数与结构均一致"
        else:
            detail = (
                f"相似函数 {pair['name']}（{pair['file']}，{pair['lines']}行）与 "
                f"{pair['other_name']}（{pair['other_file']}，{pair['other_lines']}行）结构高度一致"
            )
        hazards.append(
            {
                "target": pair["file"],
                "kind": "duplicate",
                "count": count,
                "freshness": "standing",  # 实时扫描命中即当下为真
                "detail": detail,
                "evidence": {
                    "store": "live-scan",
                    "rule": "checks.duplicate_match",
                    "count": count,
                    "first_seen": record.get("first_seen"),
                },
            }
        )

    # 预算：历史驱动（维持原语义）
    for entry in history.values():
        if not isinstance(entry, dict):
            continue
        if str(entry.get("kind") or "") != "over-budget":
            continue
        key = str(entry.get("key") or entry.get("detail") or "")
        target = key.rsplit(":", 1)[0] if ":" in key else key
        count = int(entry.get("count") or 0)
        if target and target not in commit_cache:
            commit_cache[target] = _file_last_commit(manifest.project_root, target)
        hazards.append(
            {
                "target": target or key,
                "kind": "budget",
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
        hazards.extend(_regulator_absent_hazards(events))
    except Exception:
        pass
    try:
        hazards.extend(_guard_hazards(manifest))
    except Exception:
        pass
    try:
        hazards.extend(_ungoverned_commit_hazards(manifest, events))
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
