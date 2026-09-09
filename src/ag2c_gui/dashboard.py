"""首页仪表盘：当前任务 + 异常清单 + 健康度。

房间宪法（knowledge.ag2c-gui）：数据装配与绘制分离。dashboard_model 是纯函数
（不 import imgui，可单测）；draw_dashboard 只渲染装配结果。全绿时首页近乎
空屏——最好的治理界面是没什么可看的界面。
"""

from __future__ import annotations

from typing import Any

TERMINAL_TASK_STATES = frozenset({"completed", "abandoned"})

LIFECYCLE_LABELS = {
    "constructing": "施工中",
    "verified-unmerged": "已验证待合并",
    "diverged": "已分叉",
    "merged": "已合并",
    "abandoned": "已放弃",
    "missing": "worktree 缺失",
}

MAX_GOAL_CHARS = 60
MAX_LISTED_ANOMALIES = 12
MAX_LISTED_HAZARDS = 5

#: 危房种类的城市语言（名单只负责"看得见"，每条带制度建议）。
HAZARD_LABELS = {
    "hollow": "危楼·无安全网",
    "duplicate": "双胞胎楼",
    "budget": "超重楼",
    "stale": "旧档案",
}


def _text(row: dict[str, Any] | None, key: str) -> str:
    if not isinstance(row, dict):
        return ""
    value = row.get(key)
    return str(value).strip() if value is not None else ""


def _clip(value: str, limit: int = MAX_GOAL_CHARS) -> str:
    value = " ".join(str(value).split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def open_tasks(details: dict[str, Any]) -> list[dict[str, Any]]:
    """Non-terminal task records, oldest first, shaped for the home screen."""
    tasks: list[dict[str, Any]] = []
    for task in details.get("worktrees") or []:
        if not isinstance(task, dict):
            continue
        state = _text(task, "state")
        if state in TERMINAL_TASK_STATES:
            continue
        worktree = task.get("worktree") if isinstance(task.get("worktree"), dict) else {}
        lifecycle = _text(worktree, "lifecycle")
        regulator = ""
        verifications = task.get("verifications")
        if isinstance(verifications, list) and verifications:
            last = verifications[-1]
            if isinstance(last, dict):
                reg = last.get("regulator")
                if isinstance(reg, dict):
                    regulator = _text(reg, "outcome")
        tasks.append(
            {
                "id": _text(task, "id"),
                "goal": _clip(_text(task, "goal")),
                "state": state,
                "lifecycle": lifecycle,
                "lifecycle_label": LIFECYCLE_LABELS.get(lifecycle, lifecycle or state),
                "diverged": bool(worktree.get("diverged")),
                "created_at": _text(task, "created_at"),
                "regulator": regulator,
            }
        )
    return tasks


def stale_knowledge(details: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        card
        for card in details.get("knowledge") or []
        if isinstance(card, dict) and card.get("status") == "stale"
    ]


def pending_items(details: dict[str, Any]) -> list[dict[str, Any]]:
    pending = details.get("pending") if isinstance(details.get("pending"), dict) else {}
    return [item for item in pending.get("items") or [] if isinstance(item, dict)]


def dashboard_model(details: dict[str, Any] | None, guard: dict[str, Any] | None) -> dict[str, Any]:
    """Assemble the home screen from project details + the canonical watchdog.

    Pure function: any missing or malformed input degrades to empty sections,
    never an exception — the home screen must render even when the project is
    broken, because that is exactly when the user looks at it.
    """
    details = details if isinstance(details, dict) else {}
    guard = guard if isinstance(guard, dict) else {}

    tasks = open_tasks(details)
    pending = pending_items(details)
    stale = stale_knowledge(details)

    anomalies: list[dict[str, str]] = []
    if guard.get("canonicalDirty") and not guard.get("error") and not tasks:
        anomalies.append(
            {"severity": "error", "text": "canonical 检出在非任务窗口被修改——可能有改动绕开了治理流程"}
        )
    for task in tasks:
        if task["diverged"]:
            anomalies.append({"severity": "error", "text": f"任务 {task['id']} 的 worktree 已分叉，需要处理"})
    for item in pending:
        title = _text(item, "title") or _text(item, "kind") or "未命名事项"
        hint = _text(item, "hint")
        anomalies.append({"severity": "warn", "text": f"待结算：{title}" + (f"（{hint}）" if hint else "")})
    for card in stale:
        anomalies.append({"severity": "warn", "text": f"知识卡过期：{_text(card, 'id')}"})
    census = details.get("census") if isinstance(details.get("census"), dict) else {}
    if _text(census, "error"):
        anomalies.append({"severity": "error", "text": f"普查失败：{_text(census, 'error')}"})
    index = details.get("index") if isinstance(details.get("index"), dict) else {}
    for error in index.get("errors") or []:
        anomalies.append({"severity": "error", "text": f"索引错误：{error}"})
    debt = details.get("baseline_debt") if isinstance(details.get("baseline_debt"), dict) else {}
    debt_total = int(debt.get("total") or 0)
    debt_target = int(debt.get("target") or 0)
    if debt.get("over"):
        anomalies.append(
            {"severity": "error", "text": f"基线债务超目标：当前 {debt_total}，上限 {debt_target}（只减不增，新增失败需先还债）"}
        )
    audit = details.get("audit") if isinstance(details.get("audit"), dict) else {}
    audit_pending = [item for item in audit.get("pending") or [] if isinstance(item, dict)]
    if audit_pending:
        first = _text(audit_pending[0], "id")
        severity = "error" if audit.get("due") else "warn"
        label = "抽查到期" if audit.get("due") else "抽查待办"
        anomalies.append(
            {"severity": severity, "text": f"{label}：{len(audit_pending)} 项待人工核对（如 {first}），确认点下方「已抽查」"}
        )

    # 巡逻叙事：演习（金丝雀）与拦截通报。巡逻队不巡逻，等于没有巡逻队——
    # 从未演习与演习超期本身就是警情；演习失败（变异存活/门禁漏检）是最高级警情。
    # 注意：patrol 段缺席（overlay 未运行/失败）= 未知，静默降级；只有段在场
    # 且 runs 为 0 才报"从未演习"——未知不等于未演习。
    patrol_lines: list[dict[str, str]] = []
    drill_days: list[int] = []
    patrol = details.get("patrol") if isinstance(details.get("patrol"), dict) else None
    if patrol is not None:
        drills = patrol.get("drills") if isinstance(patrol.get("drills"), dict) else {}
        interval = int(patrol.get("drill_interval_days") or 7)
        for mode in ("gate", "mutation"):
            drill = drills.get(mode) if isinstance(drills.get(mode), dict) else {}
            label = _text(drill, "label") or {"gate": "安检演习", "mutation": "消防演习"}.get(mode, mode)
            days = drill.get("days_since")
            result = _text(drill, "last_result")
            command = "ag2c canary" + (" --mode mutation" if mode == "mutation" else "")
            if not drill.get("runs"):
                anomalies.append({"severity": "warn", "text": f"{label}从未举行：巡逻队还没出过警 → 建议运行 {command}"})
                patrol_lines.append({"severity": "warn", "text": f"{label}：从未举行"})
                continue
            if isinstance(days, int):
                drill_days.append(days)
            if result == "failed":
                detail = _text(drill, "last_detail")
                anomalies.append(
                    {"severity": "error", "text": f"{label}报警：{detail or '上次演习未被拦住'}——测试可能空心，建议检查该区域并补测试"}
                )
            elif drill.get("overdue"):
                anomalies.append({"severity": "warn", "text": f"{label}超期：已 {days} 天未演习（间隔 {interval} 天）→ 建议运行 {command}"})
            verb = {"passed": "咬住了", "failed": "未被拦住！", "error": "未能执行"}.get(result, result or "未知")
            when = "从未" if not isinstance(days, int) else ("今天" if days == 0 else f"{days} 天前")
            patrol_lines.append({"severity": "error" if result == "failed" else "ok", "text": f"{label}：{when}演习，{verb}"})
        interceptions = patrol.get("interceptions") if isinstance(patrol.get("interceptions"), dict) else {}
        window = int(interceptions.get("window_days") or 30)
        patrol_lines.append(
            {"severity": "ok", "text": f"拦截通报：近 {window} 天拦截 {int(interceptions.get('in_window') or 0)} 次绕过尝试"}
        )

    # 旧城改造：危房名单（只读聚合，不动手）。hollow（安全网缺失）是最危险的
    # 一类，除列表外同时进异常清单；与 patrol 段同规约——段缺席 = 未知，静默降级。
    hazard_lines: list[dict[str, str]] = []
    hazards = details.get("hazards") if isinstance(details.get("hazards"), dict) else None
    if hazards is not None:
        items = [item for item in hazards.get("hazards") or [] if isinstance(item, dict)]
        for item in items:
            if item.get("kind") == "hollow" and not item.get("resolved"):
                anomalies.append(
                    {"severity": "warn", "text": f"危楼·无安全网：{_text(item, 'target')}——{_text(item, 'suggestion') or '补杀变异测试'}"}
                )
        for item in items[:MAX_LISTED_HAZARDS]:
            label = HAZARD_LABELS.get(str(item.get("kind") or ""), str(item.get("kind") or "危房"))
            target = _text(item, "target")
            suggestion = _text(item, "suggestion")
            resolved = "（疑似已修复）" if item.get("resolved") else ""
            hazard_lines.append(
                {
                    "severity": "error" if item.get("kind") == "hollow" and not item.get("resolved") else "warn",
                    "text": f"{label}：{target}{resolved} → {suggestion}",
                }
            )

    overflow = max(0, len(anomalies) - MAX_LISTED_ANOMALIES)
    listed = anomalies[:MAX_LISTED_ANOMALIES]
    if overflow:
        listed.append({"severity": "warn", "text": f"……另有 {overflow} 条未列出"})

    health = [
        {"label": "进行中任务", "value": len(tasks)},
        {"label": "待结算", "value": len(pending)},
        {"label": "过期卡片", "value": len(stale)},
    ]
    census_data = details.get("census") if isinstance(details.get("census"), dict) else {}
    census_households = census_data.get("households") if isinstance(census_data.get("households"), list) else []
    stale_census = sum(1 for h in census_households if isinstance(h, dict) and h.get("freshness") == "stale")
    health.append({"label": "普查陈旧", "value": stale_census})
    health.append({"label": "基线债务", "value": debt_total})
    days_since = audit.get("days_since")
    health.append({"label": "距上次抽查", "value": days_since if isinstance(days_since, int) else "—"})
    health.append({"label": "距上次演习", "value": min(drill_days) if drill_days else "—"})
    project = details.get("project") if isinstance(details.get("project"), dict) else {}
    return {
        "project": _text(project, "name"),
        "tasks": tasks,
        "anomalies": listed,
        "anomaly_count": len(anomalies),
        "health": health,
        "audit": {"pending": audit_pending, "due": bool(audit.get("due"))},
        "patrol": patrol_lines,
        "hazards": hazard_lines,
    }


def draw_dashboard(model: dict[str, Any]) -> None:
    """Render the assembled model. No data decisions here — only drawing."""
    from imgui_bundle import imgui

    if model["project"]:
        imgui.text_disabled(model["project"])

    # 健康度：几个数，零是绿色，非零吸注意力；"—"（无数据）灰色静默。
    for i, item in enumerate(model["health"]):
        if i:
            imgui.same_line(0.0, 28.0)
        raw_value = item["value"]
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            imgui.text_disabled(f"{item['label']} —")
            continue
        color = (0.45, 0.80, 0.50, 1.0) if value == 0 else (0.95, 0.70, 0.30, 1.0)
        imgui.text_colored(color, f"{item['label']} {value}")
    imgui.separator()

    imgui.text("当前任务")
    if not model["tasks"]:
        imgui.text_disabled("当前没有进行中的任务")
    for task in model["tasks"]:
        color = (0.55, 0.75, 0.95, 1.0) if not task["diverged"] else (0.95, 0.35, 0.30, 1.0)
        imgui.text_colored(color, f"● {task['lifecycle_label']}")
        imgui.same_line(0.0, 10.0)
        imgui.text_wrapped(task["goal"] or task["id"])
        regulator = task.get("regulator") or ""
        if regulator:
            label, reg_color = {
                "passed": ("监管：通过", (0.45, 0.80, 0.50, 1.0)),
                "rejected": ("监管：打回", (0.95, 0.35, 0.30, 1.0)),
                "unavailable": ("监管：本次缺 AI 监管", (0.95, 0.70, 0.30, 1.0)),
            }.get(regulator, (f"监管：{regulator}", (0.95, 0.70, 0.30, 1.0)))
            imgui.text_colored(reg_color, label)
    imgui.separator()

    imgui.text("巡逻记录")
    if not model["patrol"]:
        imgui.text_disabled("还没有巡逻记录")
    for line in model["patrol"]:
        color = {
            "ok": (0.45, 0.80, 0.50, 1.0),
            "warn": (0.95, 0.70, 0.30, 1.0),
            "error": (0.95, 0.35, 0.30, 1.0),
        }.get(line["severity"], (0.95, 0.70, 0.30, 1.0))
        imgui.text_colored(color, "●")
        imgui.same_line(0.0, 8.0)
        imgui.text_wrapped(line["text"])
    imgui.separator()

    imgui.text("旧城改造")
    if not model["hazards"]:
        imgui.text_disabled("危房名单是空的")
    for line in model["hazards"]:
        color = (0.95, 0.35, 0.30, 1.0) if line["severity"] == "error" else (0.95, 0.70, 0.30, 1.0)
        imgui.text_colored(color, "▲")
        imgui.same_line(0.0, 8.0)
        imgui.text_wrapped(line["text"])
    imgui.separator()

    imgui.text("异常清单")
    if not model["anomalies"]:
        imgui.text_disabled("没有需要注意的事")
    for anomaly in model["anomalies"]:
        color = (0.95, 0.35, 0.30, 1.0) if anomaly["severity"] == "error" else (0.95, 0.70, 0.30, 1.0)
        imgui.text_colored(color, "!" if anomaly["severity"] == "error" else "△")
        imgui.same_line(0.0, 8.0)
        imgui.text_wrapped(anomaly["text"])
