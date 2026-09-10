"""首页仪表盘：三区结构——需要你处理 / 系统警情 / 记录（仅供查阅）。

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

#: 风险种类标签：大白话+专业，单独拎出来无需懂城市隐喻即可理解。
HAZARD_LABELS = {
    "hollow": "测试无效风险",
    "duplicate": "重复代码",
    "budget": "超出预算",
    "stale": "普查过期",
}

#: 检查阶段标签：阴影行用，大白话（代码库内阶段名只有英文）。
STAGE_LABELS = {
    "static": "静态检查",
    "floor": "房间测试",
    "boundary": "边界测试",
    "scenario": "场景测试",
}

#: 阴影行里最多点名的跳过 checker 数，超出折叠为"等 N 项"。
MAX_LISTED_SHADOW_SKIPS = 2

#: 注意力总闸门：决策事项的类别标签（顺序即分解顺序）。只有人能拍板的才算
#: 决策——系统错误与演习警情是排队项，不进这个数。
ATTENTION_LABELS = {
    "pending": "待结算",
    "audit": "抽查待办",
    "diverged": "任务分叉",
    "stale": "过期卡片",
}

#: 调色板：颜色是注意力语言，全看板的颜色只能来自 severity_color /
#: zone_header_color，绘制代码里不出现硬编码 RGB。跳出度阶梯——
#: 红（高危，立即行动，靠色相与饱和度跳出，只给 error）> 决策琥珀（需要你
#: 拍板）> 暗琥珀（知情即可）> 暗绿（正常指示）> 灰（记录/无数据）。
DANGER = (0.95, 0.30, 0.25, 1.0)
DECISION = (0.95, 0.70, 0.25, 1.0)
NOTICE = (0.70, 0.53, 0.22, 1.0)
OK_DIM = (0.40, 0.58, 0.42, 1.0)
MUTED = (0.48, 0.48, 0.50, 1.0)

_ZONE_SEVERITY_COLORS = {
    ("action", "error"): DANGER,
    ("action", "warn"): DECISION,
    ("alert", "error"): DANGER,
    ("alert", "warn"): NOTICE,
    ("record", "error"): DANGER,
    ("record", "warn"): NOTICE,
    ("record", "ok"): OK_DIM,
}

_ZONE_HEADER_COLORS = {
    "action": DECISION,
    "alert": NOTICE,
    "record": MUTED,
}


def severity_color(zone: str, severity: str) -> tuple[float, float, float, float]:
    """唯一的颜色来源：区 × 严重度 → 色值。未知组合静默降级为灰。"""
    return _ZONE_SEVERITY_COLORS.get((zone, severity), MUTED)


def zone_header_color(zone: str) -> tuple[float, float, float, float]:
    """分区标题色：与区内最高语义同色，让标题本身预示内容等级。"""
    return _ZONE_HEADER_COLORS.get(zone, MUTED)


#: 视觉主体的字号倍数：主体（注意力闸门）以大字独占顶部，其余皆为陪体/背景。
HERO_FONT_SCALE = 1.6


def hero_block(model: dict[str, Any] | None) -> dict[str, Any]:
    """视觉主体：注意力闸门即页面主体。纯函数，垃圾输入降级为空主体。"""
    model = model if isinstance(model, dict) else {}
    attention = model.get("attention") if isinstance(model.get("attention"), dict) else {}
    count = attention.get("count")
    actions = model.get("actions")
    return {
        "text": str(attention.get("text") or ""),
        "count": int(count) if isinstance(count, int) else 0,
        "has_actions": isinstance(actions, list) and bool(actions),
    }


def _text(row: dict[str, Any] | None, key: str) -> str:
    if not isinstance(row, dict):
        return ""
    value = row.get(key)
    return str(value).strip() if value is not None else ""


def _clip(value: str, limit: int = MAX_GOAL_CHARS) -> str:
    value = " ".join(str(value).split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _cap_listed(lines: list[dict[str, str]], limit: int = MAX_LISTED_ANOMALIES) -> list[dict[str, str]]:
    """Cap a zone list, folding the overflow into a fixed summary line."""
    overflow = max(0, len(lines) - limit)
    listed = lines[:limit]
    if overflow:
        listed.append({"severity": "warn", "text": f"……另有 {overflow} 条未列出"})
    return listed


def verification_shadow(verification: dict[str, Any]) -> list[str]:
    """绿灯的阴影：本次验证"没有检查什么"，固定模板，制度在说话。

    数据全部来自验证记录既有字段（acceptance / checker_results / regulator），
    不新增采集。任何字段缺失或畸形都静默跳过对应条目——未知不编造。
    """
    shadow: list[str] = []
    acceptance = verification.get("acceptance")
    if isinstance(acceptance, dict) and acceptance:
        if acceptance.get("complete") != "passed":
            shadow.append("未做全量验收")
        for stage, label in STAGE_LABELS.items():
            state = acceptance.get(stage)
            if state == "not-run":
                shadow.append(f"{label}未运行")
            elif state == "not-applicable":
                shadow.append(f"{label}未配置")
    skipped = [
        _text(item, "id")
        for item in verification.get("checker_results") or []
        if isinstance(item, dict) and item.get("status") == "skipped" and _text(item, "id")
    ]
    if skipped:
        named = "、".join(skipped[:MAX_LISTED_SHADOW_SKIPS])
        if len(skipped) > MAX_LISTED_SHADOW_SKIPS:
            named += f" 等 {len(skipped)} 项"
        shadow.append(f"跳过的检查：{named}")
    if not isinstance(verification.get("regulator"), dict):
        shadow.append("无 AI 监管记录")
    return shadow


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
        shadow: list[str] = []
        verifications = task.get("verifications")
        if isinstance(verifications, list) and verifications:
            last = verifications[-1]
            if isinstance(last, dict):
                reg = last.get("regulator")
                if isinstance(reg, dict):
                    regulator = _text(reg, "outcome")
                shadow = verification_shadow(last)
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
                "shadow": shadow,
            }
        )
    return tasks


def stale_knowledge(details: dict[str, Any]) -> list[dict[str, Any]]:
    knowledge = details.get("knowledge")
    if not isinstance(knowledge, list):
        return []
    return [card for card in knowledge if isinstance(card, dict) and card.get("status") == "stale"]


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

    # 分区装配：actions = 需要人拍板/动手的决策项（与注意力闸门同口径），每条
    # 带动作提示；alerts = 系统级异常，人只需知情、处理责任在系统/AI。原
    # "异常清单"按此拆成两区；anomalies 键保留为两区合并（兼容旧消费方）。
    actions: list[dict[str, str]] = []
    alerts: list[dict[str, str]] = []
    if guard.get("canonicalDirty") and not guard.get("error") and not tasks:
        alerts.append(
            {"severity": "error", "text": "canonical 检出在非任务窗口被修改——可能有改动绕开了治理流程"}
        )
    for task in tasks:
        if task["diverged"]:
            actions.append(
                {"severity": "error", "text": f"任务 {task['id']} 的 worktree 已分叉 → ag2c task refresh 同步，或 task abandon 放弃"}
            )
    for item in pending:
        title = _text(item, "title") or _text(item, "kind") or "未命名事项"
        hint = _text(item, "hint") or "运行 ag2c govern settle 结算"
        actions.append({"severity": "warn", "text": f"待结算：{title} → {hint}"})
    for card in stale:
        actions.append(
            {"severity": "warn", "text": f"知识卡过期：{_text(card, 'id')} → 复核后用 ag2c govern apply 更新该卡"}
        )
    census = details.get("census") if isinstance(details.get("census"), dict) else {}
    if _text(census, "error"):
        alerts.append({"severity": "error", "text": f"普查失败：{_text(census, 'error')}"})
    index = details.get("index") if isinstance(details.get("index"), dict) else {}
    for error in index.get("errors") or []:
        alerts.append({"severity": "error", "text": f"索引错误：{error}"})
    debt = details.get("baseline_debt") if isinstance(details.get("baseline_debt"), dict) else {}
    debt_total = int(debt.get("total") or 0)
    debt_target = int(debt.get("target") or 0)
    if debt.get("over"):
        alerts.append(
            {"severity": "error", "text": f"基线债务超目标：当前 {debt_total}，上限 {debt_target}（只减不增，新增失败需先还债）"}
        )
    audit = details.get("audit") if isinstance(details.get("audit"), dict) else {}
    audit_pending = [item for item in audit.get("pending") or [] if isinstance(item, dict)]
    if audit_pending:
        first = _text(audit_pending[0], "id")
        severity = "error" if audit.get("due") else "warn"
        label = "抽查到期" if audit.get("due") else "抽查待办"
        actions.append(
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
            label = _text(drill, "label") or {"gate": "门禁演习", "mutation": "变异演习"}.get(mode, mode)
            days = drill.get("days_since")
            result = _text(drill, "last_result")
            command = "ag2c canary" + (" --mode mutation" if mode == "mutation" else "")
            if not drill.get("runs"):
                alerts.append({"severity": "warn", "text": f"{label}从未举行：还没有验证过拦截能力 → 建议运行 {command}"})
                patrol_lines.append({"severity": "warn", "text": f"{label}：从未举行"})
                continue
            if isinstance(days, int):
                drill_days.append(days)
            if result == "failed":
                detail = _text(drill, "last_detail")
                alerts.append(
                    {"severity": "error", "text": f"{label}失败：{detail or '植入的缺陷未被拦截'}——测试可能无效，建议检查该区域并补测试"}
                )
            elif drill.get("overdue"):
                alerts.append({"severity": "warn", "text": f"{label}超期：已 {days} 天未演习（间隔 {interval} 天）→ 建议运行 {command}"})
            verb = {"passed": "已通过（缺陷被拦截）", "failed": "失败：缺陷未被拦截", "error": "未能执行"}.get(result, result or "未知")
            when = "从未" if not isinstance(days, int) else ("今天" if days == 0 else f"{days} 天前")
            patrol_lines.append({"severity": "error" if result == "failed" else "ok", "text": f"{label}：{when}{verb}"})
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
                alerts.append(
                    {"severity": "warn", "text": f"测试无效风险：{_text(item, 'target')}——{_text(item, 'suggestion') or '补充能捕获该类缺陷的测试'}"}
                )
        for item in items[:MAX_LISTED_HAZARDS]:
            label = HAZARD_LABELS.get(str(item.get("kind") or ""), str(item.get("kind") or "危房"))
            target = _text(item, "target")
            suggestion = _text(item, "suggestion")
            resolved = "（疑似已修复）" if item.get("resolved") else ""
            if item.get("freshness") == "unconfirmed":
                resolved += "（待复核：文件已改动，记录可能已死）"
            hazard_lines.append(
                {
                    "severity": "error" if item.get("kind") == "hollow" and not item.get("resolved") else "warn",
                    "text": f"{label}：{target}{resolved} → {suggestion}",
                }
            )

    # 治理成本：token 会计（粗估，估算规则随数据返回）。段缺席 = 未知，静默降级。
    # 文字全部是固定模板——制度在说话，不是 AI 在说话（反向引导收口规则 1）。
    token_lines: list[dict[str, str]] = []
    token = details.get("token") if isinstance(details.get("token"), dict) else None
    if token is not None:
        month_cost = token.get("month_cost_usd")
        total_cost = token.get("cost_usd")
        month_tokens = token.get("month_tokens")
        if isinstance(month_cost, (int, float)) and isinstance(total_cost, (int, float)):
            token_lines.append({"severity": "ok", "text": f"本月治理成本约 ${month_cost:.2f}（{int(month_tokens or 0):,} tokens，粗估）；累计 ${total_cost:.2f}"})
        rework = [item for item in token.get("top_rework") or [] if isinstance(item, dict)]
        if rework:
            worst = rework[0]
            token_lines.append(
                {"severity": "warn", "text": f"返工最重：{_text(worst, 'task')}（verify {int(worst.get('verify_runs') or 0)} 次）——返工是治理成本的乘数"}
            )

    # 区①逐条列出、不截断——与注意力闸门数字一一对应是产品承诺，折叠决策项
    # 等于隐瞒。只有区②系统警情截断（溢出折叠为固定汇总行）。
    alerts_listed = _cap_listed(alerts)

    # 注意力总闸门：每天向人类索要的决策次数有硬上限。这一行是全页第一行，
    # 其余一切排队、不许插队——这行字本身是产品承诺：我尊重你的注意力预算。
    # 只数"需要人拍板"的事；系统错误、演习警情是排队项，不进这个数。
    attention_counts = {
        "pending": len(pending),
        "audit": len(audit_pending),
        "diverged": sum(1 for task in tasks if task["diverged"]),
        "stale": len(stale),
    }
    attention_total = sum(attention_counts.values())
    if attention_total:
        breakdown = "、".join(
            f"{ATTENTION_LABELS[kind]} {count}"
            for kind, count in attention_counts.items()
            if count
        )
        attention_text = f"今天需要你决策的事：{attention_total} 件（{breakdown}）"
    else:
        attention_text = "今天没有需要你决策的事"
    attention = {"count": attention_total, "text": attention_text}

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
    if hazards is not None:
        dismissed = hazards.get("dismissed")
        health.append({"label": "已豁免项", "value": dismissed if isinstance(dismissed, int) else 0})
    project = details.get("project") if isinstance(details.get("project"), dict) else {}
    records = {
        "health": health,
        "tasks": tasks,
        "patrol": patrol_lines,
        "hazards": hazard_lines,
        "token": token_lines,
    }
    return {
        "project": _text(project, "name"),
        "attention": attention,
        "tasks": tasks,
        "actions": actions,
        "alerts": alerts_listed,
        "records": records,
        "anomalies": actions + alerts_listed,
        "anomaly_count": len(actions) + len(alerts),
        "health": health,
        "audit": {"pending": audit_pending, "due": bool(audit.get("due"))},
        "patrol": patrol_lines,
        "hazards": hazard_lines,
        "token": token_lines,
    }


def draw_dashboard(model: dict[str, Any]) -> None:
    """Render the assembled model. No data decisions here — only drawing."""
    from imgui_bundle import imgui

    if model["project"]:
        imgui.text_disabled(model["project"])

    # 视觉主体（摄影的主体）：注意力闸门放大独占顶部，是页面唯一焦点。
    # 大字用 push_font/pop_font 成对实现（本版 imgui_bundle 无 set_window_font_scale）。
    hero = hero_block(model)
    if hero["text"]:
        imgui.spacing()
        imgui.push_font(None, imgui.get_font_size() * HERO_FONT_SCALE)
        try:
            imgui.text_colored(DECISION if hero["count"] else OK_DIM, hero["text"])
        finally:
            imgui.pop_font()
        imgui.spacing()
        imgui.separator()

    # 决策项直接跟随主体（主体即标题，不再有小标题）。主体已说"没有"时不重复空态。
    actions = model.get("actions") or []
    if actions:
        for item in actions:
            imgui.text_colored(severity_color("action", item["severity"]), "!" if item["severity"] == "error" else "△")
            imgui.same_line(0.0, 8.0)
            imgui.text_wrapped(item["text"])
        imgui.separator()
    elif hero["count"]:
        imgui.text_disabled("没有需要你处理的事")
        imgui.separator()

    # 区② 系统警情：陪体，正文字号、暗琥珀标题，退居次要。
    alerts = model.get("alerts") or []
    imgui.text_colored(zone_header_color("alert"), "系统警情")
    if not alerts:
        imgui.text_disabled("没有系统警情")
    for item in alerts:
        imgui.text_colored(severity_color("alert", item["severity"]), "!" if item["severity"] == "error" else "△")
        imgui.same_line(0.0, 8.0)
        imgui.text_wrapped(item["text"])
    imgui.separator()

    # 区③ 记录：背景，默认折叠为单行，点击才展开——收起时不占视觉空间。
    records = model.get("records") if isinstance(model.get("records"), dict) else {}
    rec_health = records.get("health") or []
    rec_tasks = records.get("tasks") or []
    rec_patrol = records.get("patrol") or []
    rec_hazards = records.get("hazards") or []
    rec_token = records.get("token") or []
    if not imgui.collapsing_header("记录 · 仅供查阅"):
        return
    if not (rec_tasks or rec_patrol or rec_hazards or rec_token):
        imgui.text_disabled("暂无记录")
        return

    # 健康度：几个数，零是暗绿（正常指示），非零暗琥珀（记录区提示）；"—"灰色静默。
    for i, item in enumerate(rec_health):
        if i:
            imgui.same_line(0.0, 28.0)
        raw_value = item["value"]
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            imgui.text_disabled(f"{item['label']} —")
            continue
        imgui.text_colored(OK_DIM if value == 0 else NOTICE, f"{item['label']} {value}")
    imgui.separator()

    imgui.text("当前任务")
    if not rec_tasks:
        imgui.text_disabled("当前没有进行中的任务")
    for task in rec_tasks:
        imgui.text_colored(DANGER if task["diverged"] else MUTED, f"● {task['lifecycle_label']}")
        imgui.same_line(0.0, 10.0)
        imgui.text_wrapped(task["goal"] or task["id"])
        regulator = task.get("regulator") or ""
        if regulator:
            label, reg_color = {
                "passed": ("监管：通过", OK_DIM),
                "rejected": ("监管：打回", DANGER),
                "unavailable": ("监管：本次缺 AI 监管", NOTICE),
            }.get(regulator, (f"监管：{regulator}", NOTICE))
            imgui.text_colored(reg_color, label)
        # 绿灯带阴影：每个"通过"旁标注本次未检查什么，让绿灯自带存疑。
        shadow = task.get("shadow") or []
        if shadow:
            imgui.text_disabled("本次未检查：" + "；".join(shadow))
    imgui.separator()

    imgui.text("巡逻记录")
    if not rec_patrol:
        imgui.text_disabled("还没有巡逻记录")
    for line in rec_patrol:
        imgui.text_colored(severity_color("record", line["severity"]), "●")
        imgui.same_line(0.0, 8.0)
        imgui.text_wrapped(line["text"])
    imgui.separator()

    imgui.text("旧城改造")
    if not rec_hazards:
        imgui.text_disabled("没有检测到风险项")
    for line in rec_hazards:
        imgui.text_colored(severity_color("record", line["severity"]), "▲")
        imgui.same_line(0.0, 8.0)
        imgui.text_wrapped(line["text"])

    if rec_token:
        imgui.separator()
        imgui.text("治理成本")
        for line in rec_token:
            imgui.text_colored(severity_color("record", line["severity"]), "◆")
            imgui.same_line(0.0, 8.0)
            imgui.text_wrapped(line["text"])
