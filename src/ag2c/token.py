"""token 会计：把治理成本折算成钱，让市长看见治理的代价。

治理不是免费的：每次会话要背 MCP 工具 schema（固定税），每次开工要注入
知识卡指导（引导注入），每次 verify 要重发 diff 上下文（验证成本，重试
即返工）。这些 token 都是钱。本模块只做**粗估**——不引 tokenizer 依赖，
每个数字都附带估算规则，宁可透明地粗糙，不可精确地唬人。

数据源全部是账本既有事件（task-started / task-verification），因此可以
回溯历史。估算参数可在 policy.json 的 "token" 节覆盖：

    "token": {
        "price_per_million_usd": 2.0,
        "session_tax_tokens": 3000,
        "guidance_tokens_per_task": 4000,
        "verify_tokens_base": 2000,
        "verify_tokens_per_file": 300
    }

与 patrol / hazard 同一条军规：任何输入异常都降级为空报告，绝不抛异常。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .ledger import read_events
from .util import parse_iso8601

TOKEN_SCHEMA = "ag2c.token.v1"

#: 默认估算参数。定价取主流编程模型中间档位；token 按 ~4 字符/token 粗估。
DEFAULTS = {
    "price_per_million_usd": 2.0,
    # MCP 工具 schema 每次会话常驻系统提示：约 20 个工具 × 平均 schema 体积
    "session_tax_tokens": 3000,
    # task_start 的指导注入：谱系卡片 + 复用菜单 + 写法约定
    "guidance_tokens_per_task": 4000,
    # 单次 verify：任务上下文 + 检查结果回读
    "verify_tokens_base": 2000,
    # verify 按变更文件数缩放：每个文件的 diff 都要进上下文
    "verify_tokens_per_file": 300,
}


def _config(manifest) -> dict[str, float]:
    """读 policy.json 的 token 节覆盖默认值；任何损坏都用默认。"""
    config = dict(DEFAULTS)
    try:
        raw = json.loads(manifest.policy_path.read_text(encoding="utf-8"))
        section = raw.get("token") if isinstance(raw, dict) else None
        if isinstance(section, dict):
            for key in DEFAULTS:
                value = section.get(key)
                if isinstance(value, (int, float)) and value >= 0:
                    config[key] = float(value)
    except (OSError, ValueError):
        pass
    return config


_parse_time = parse_iso8601


def token_report(manifest, *, now: datetime | None = None) -> dict[str, Any]:
    """汇总治理 token 成本。任何输入异常都降级为空报告，绝不抛异常。"""
    now = now or datetime.now(timezone.utc)
    empty = {
        "schema": TOKEN_SCHEMA,
        "generated_at": now.isoformat(),
        "config": dict(DEFAULTS),
        "tasks": 0,
        "verify_runs": 0,
        "rework_runs": 0,
        "tokens": {"session_tax": 0, "guidance": 0, "verify": 0, "total": 0},
        "cost_usd": 0.0,
        "month_cost_usd": 0.0,
        "month_tokens": 0,
        "top_rework": [],
    }
    try:
        events = read_events(manifest.ledger_path)
    except Exception:
        return empty
    config = _config(manifest)
    try:
        started: list[datetime | None] = []
        verify_runs = 0
        verify_tokens = 0
        attempts: dict[str, int] = {}
        verify_times: list[datetime | None] = []
        for event in events:
            if not isinstance(event, dict):
                continue
            kind = event.get("event_type")
            occurred = _parse_time(event.get("occurred_at"))
            if kind == "task-started":
                started.append(occurred)
            elif kind == "task-verification":
                payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
                verify_runs += 1
                verify_times.append(occurred)
                files = payload.get("changed_paths")
                file_count = len(files) if isinstance(files, list) else 0
                verify_tokens += int(config["verify_tokens_base"] + config["verify_tokens_per_file"] * file_count)
                task_id = str(payload.get("task_id") or "")
                if task_id:
                    attempts[task_id] = attempts.get(task_id, 0) + 1
        session_tax = int(len(started) * config["session_tax_tokens"])
        guidance = int(len(started) * config["guidance_tokens_per_task"])
        total = session_tax + guidance + verify_tokens
        cost = total / 1_000_000 * config["price_per_million_usd"]
        # 返工 = 同一任务的第 2 次及以后 verify
        rework_runs = sum(count - 1 for count in attempts.values() if count > 1)
        top_rework = [
            {"task": task_id, "verify_runs": count}
            for task_id, count in sorted(attempts.items(), key=lambda item: -item[1])
            if count > 1
        ][:5]
        # 本月成本：按事件时间归属，三种税各自过滤
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_tasks = sum(1 for t in started if t is not None and t >= month_start)
        month_verify_tokens = 0
        month_verify_runs = 0
        for event in events:
            if not isinstance(event, dict) or event.get("event_type") != "task-verification":
                continue
            occurred = _parse_time(event.get("occurred_at"))
            if occurred is None or occurred < month_start:
                continue
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            files = payload.get("changed_paths")
            file_count = len(files) if isinstance(files, list) else 0
            month_verify_runs += 1
            month_verify_tokens += int(config["verify_tokens_base"] + config["verify_tokens_per_file"] * file_count)
        month_tokens = int(month_tasks * (config["session_tax_tokens"] + config["guidance_tokens_per_task"])) + month_verify_tokens
        return {
            "schema": TOKEN_SCHEMA,
            "generated_at": now.isoformat(),
            "config": config,
            "tasks": len(started),
            "verify_runs": verify_runs,
            "rework_runs": rework_runs,
            "tokens": {"session_tax": session_tax, "guidance": guidance, "verify": verify_tokens, "total": total},
            "cost_usd": round(cost, 4),
            "month_cost_usd": round(month_tokens / 1_000_000 * config["price_per_million_usd"], 4),
            "month_tokens": month_tokens,
            "top_rework": top_rework,
        }
    except Exception:
        return empty
