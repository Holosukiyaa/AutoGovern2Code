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


COST_REPORT_SCHEMA = "ag2c.cost-report.v1"


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _mtok(tokens: int) -> float:
    return round(tokens / 1_000_000, 6)


def _empty_cost_report(now: datetime) -> dict[str, Any]:
    zero_tokens = {"input": 0, "output": 0, "total": 0, "mtok": 0.0}
    return {
        "schema": COST_REPORT_SCHEMA,
        "generated_at": now.isoformat(),
        "unit": "MTok",
        "efficiency": {
            "tasks": 0,
            "verify_runs": 0,
            "rounds_per_task": None,
            "mean_task_seconds": None,
            "verify_failure_rate": None,
        },
        "economy": {
            "regulator": {**zero_tokens, "by_model": []},
            "self_report": {**zero_tokens, "inferred": True},
        },
        "effectiveness": {
            "completed": 0,
            "first_pass_rate": None,
            "regulator_reject_rate": None,
            "post_delivery_fixes": 0,
        },
    }


def cost_report(manifest, *, now: datetime | None = None) -> dict[str, Any]:
    """开发成本三腿仪表。纯读账本；不折钱、不拦截。任何异常降级为空报告。"""
    now = now or datetime.now(timezone.utc)
    empty = _empty_cost_report(now)
    try:
        events = read_events(manifest.ledger_path)
    except Exception:
        return empty
    try:
        started: dict[str, datetime | None] = {}
        completed_at: dict[str, datetime | None] = {}
        completed_kind: dict[str, str] = {}
        verifies: dict[str, list[dict[str, Any]]] = {}
        reg_in = 0
        reg_out = 0
        by_model: dict[str, list[int]] = {}
        self_in = 0
        self_out = 0
        regulator_decided = 0
        regulator_rejected = 0
        for event in events:
            if not isinstance(event, dict):
                continue
            kind = event.get("event_type")
            occurred = _parse_time(event.get("occurred_at"))
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            task_id = str(payload.get("task_id") or "")
            if kind == "task-started" and task_id:
                started.setdefault(task_id, occurred)
            elif kind == "task-verification":
                verifies.setdefault(task_id or "_", []).append(payload)
                regulator = payload.get("regulator") if isinstance(payload.get("regulator"), dict) else {}
                outcome = str(regulator.get("outcome") or "")
                if outcome in {"passed", "rejected"}:
                    regulator_decided += 1
                    if outcome == "rejected":
                        regulator_rejected += 1
                usage = regulator.get("usage") if isinstance(regulator.get("usage"), dict) else None
                if usage and usage.get("source") == "regulator-api":
                    raw_in = usage.get("input")
                    raw_out = usage.get("output")
                    if isinstance(raw_in, int) and isinstance(raw_out, int) and raw_in >= 0 and raw_out >= 0:
                        reg_in += raw_in
                        reg_out += raw_out
                        model = str(usage.get("model") or "unknown")
                        bucket = by_model.setdefault(model, [0, 0])
                        bucket[0] += raw_in
                        bucket[1] += raw_out
            elif kind == "task-completed" and task_id:
                completed_at[task_id] = occurred
                completed_kind[task_id] = str(payload.get("kind") or "")
                report = payload.get("cost_self_report") if isinstance(payload.get("cost_self_report"), dict) else {}
                tokens = report.get("estimated_tokens") if isinstance(report.get("estimated_tokens"), dict) else {}
                raw_in = tokens.get("input")
                raw_out = tokens.get("output")
                if isinstance(raw_in, int) and isinstance(raw_out, int) and raw_in >= 0 and raw_out >= 0:
                    self_in += raw_in
                    self_out += raw_out
        verify_runs = sum(len(items) for items in verifies.values())
        failed = sum(1 for items in verifies.values() for item in items if not item.get("passed", False))
        durations: list[float] = []
        for task_id, end in completed_at.items():
            begin = started.get(task_id)
            if begin is not None and end is not None:
                durations.append((end - begin).total_seconds())
        first_pass = 0
        for task_id in completed_at:
            items = verifies.get(task_id) or []
            if len(items) == 1 and items[0].get("passed"):
                first_pass += 1
        post_fixes = sum(1 for item_kind in completed_kind.values() if item_kind == "fix")
        started_n = len(started)
        completed_n = len(completed_at)
        model_rows = [
            {"model": model, "input": pair[0], "output": pair[1], "mtok": _mtok(pair[0] + pair[1])}
            for model, pair in sorted(by_model.items())
        ]
        return {
            "schema": COST_REPORT_SCHEMA,
            "generated_at": now.isoformat(),
            "unit": "MTok",
            "efficiency": {
                "tasks": started_n,
                "verify_runs": verify_runs,
                "rounds_per_task": _rate(verify_runs, started_n),
                "mean_task_seconds": round(sum(durations) / len(durations), 1) if durations else None,
                "verify_failure_rate": _rate(failed, verify_runs),
            },
            "economy": {
                "regulator": {
                    "input": reg_in,
                    "output": reg_out,
                    "total": reg_in + reg_out,
                    "mtok": _mtok(reg_in + reg_out),
                    "by_model": model_rows,
                },
                "self_report": {
                    "input": self_in,
                    "output": self_out,
                    "total": self_in + self_out,
                    "mtok": _mtok(self_in + self_out),
                    "inferred": True,
                },
            },
            "effectiveness": {
                "completed": completed_n,
                "first_pass_rate": _rate(first_pass, completed_n),
                "regulator_reject_rate": _rate(regulator_rejected, regulator_decided),
                "post_delivery_fixes": post_fixes,
            },
        }
    except Exception:
        return empty
